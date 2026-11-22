#!/usr/bin/env python3
"""Consent-based geolocation teaching demo; local Django server + optional ngrok."""
import argparse
import os
import secrets
import signal
import sys
import threading
from datetime import datetime, timezone
from queue import Queue, Empty

from django.conf import settings
from django.core.management import execute_from_command_line
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.urls import path
from django.views.decorators.csrf import csrf_protect

##imported from GHOST IN THE SSH

from django.views.decorators.csrf import ensure_csrf_cookie
import dj_database_url

if not settings.configured:
    render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    allowed_hosts = ["localhost", "127.0.0.1"]
    if render_host:
        allowed_hosts.append(render_host)

    settings.configure(
        DEBUG=False,
        SECRET_KEY=os.environ["SECRET_KEY"],
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=allowed_hosts,
        MIDDLEWARE=[
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
],
        INSTALLED_APPS=[
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
],
DATABASES={
    "default": dj_database_url.config(
        default="sqlite:///db.sqlite3",
        conn_max_age=0,
        conn_health_checks=True,
        ssl_require=bool(os.environ.get("DATABASE_URL")),
    )
},
USE_TZ=True,
SESSION_COOKIE_SECURE=True,
SESSION_COOKIE_HTTPONLY=True,
SESSION_COOKIE_SAMESITE="Lax",
CSRF_COOKIE_SECURE=True,
CSRF_COOKIE_SAMESITE="Lax",
SESSION_COOKIE_AGE=3600,
SECURE_PROXY_SSL_HEADER=(
    "HTTP_X_FORWARDED_PROTO",
    "https"
),
    )
######

EVENTS = Queue()
TOKEN = secrets.token_urlsafe(24)

HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Darknet Dropspot</title><style>body{font:16px system-ui;max-width:540px;margin:10vh auto;padding:1.5rem;line-height:1.5}button{padding:.8rem 1.2rem;font-size:1rem}#status{white-space:pre-wrap}</style></head><body><h1>Quick Access</h1><p>This is the new portal for seeing where the next dead drop will be.</p><button id="share">Register for drop</button><p id="status" role="status"></p><script>
const status=document.getElementById('status');
document.getElementById('share').onclick=()=>{
 if(!navigator.geolocation){status.textContent='Geolocation is not supported.';return;}
 status.textContent='Waiting for browser permission…';
 navigator.geolocation.getCurrentPosition(async pos=>{
  try{
   const resp=await fetch('/submit',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1]||''},body:JSON.stringify({latitude:pos.coords.latitude,longitude:pos.coords.longitude})});
   if(!resp.ok)throw Error('Server returned '+resp.status);
   status.textContent='Location set, Gho$t will be informed. Latitude: '+pos.coords.latitude+'; Longitude: '+pos.coords.longitude;
  }catch(e){status.textContent='Unable to share location: '+e.message;}
 },err=>status.textContent='Location not shared: '+err.message,{enableHighAccuracy:true,timeout:15000,maximumAge:0});
};
</script></body></html>'''

@ensure_csrf_cookie
def index(request):
    return HttpResponse(HTML)

@csrf_protect
def submit(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    import json
    try:
        payload = json.loads(request.body)
        lat = float(payload['latitude'])
        lon = float(payload['longitude'])

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError('Invalid coordinates')

    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid coordinates'}, status=400)

    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.authorized_locations (latitude, longitude)
            VALUES (%s, %s)
            """,
            [lat, lon],
        )

    return JsonResponse({'ok': True})

from django.contrib.auth import authenticate, login
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods
from django.utils.html import escape

@require_http_methods(["GET", "POST"])
@csrf_protect
@ensure_csrf_cookie
def dashboard_login(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect("/dashboard/")

    error = ""

    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)

        if user is not None and user.is_active and user.is_superuser:
            login(request, user)
            return redirect("/dashboard/")

        error = "<p>Invalid credentials.</p>"

    return HttpResponse(f"""
    <!doctype html>
    <html lang="en">
    <head><meta charset="utf-8"><title>GHOST-EM Login</title></head>
    <body>
      <h1>GHOST-EM Administrator Login</h1>
      {error}
      <form method="post">
        <input type="hidden" name="csrfmiddlewaretoken"
               value="{escape(get_token(request))}">
        <label>Username <input name="username" required></label>
        <label>Password <input type="password" name="password" required></label>
        <button type="submit">Sign in</button>
      </form>
    </body>
    </html>
    """)
##

from django.contrib.auth.decorators import user_passes_test

from django.contrib.auth.decorators import user_passes_test
from django.db import connection
from django.utils.html import escape

@user_passes_test(
    lambda user: user.is_authenticated and user.is_superuser,
    login_url="/dashboard/login/"
)
def dashboard(request):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM public.authorized_locations
            WHERE expires_at > NOW()
        """)
        count = cursor.fetchone()[0]

    return HttpResponse(f"""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <title>GHOST-EM Dashboard</title>
    </head>
    <body>
        <h1>GHOST-EM Dashboard</h1>
        <p>Administrator authentication successful.</p>
        <h2>Authorized submissions</h2>
        <p>Active records: {count}</p>
        <p>Retention period: 7 days</p>
        <p>Individual location records are not displayed yet.</p>
    </body>
    </html>
    """)
##

urlpatterns = [
    path("", index),
    path("submit", submit),
    path("dashboard/login/", dashboard_login),
    path("dashboard/", dashboard),
]

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

def main():
    parser=argparse.ArgumentParser(description='Consent-based Track-Em educational demo')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--tunnel',action='store_true',help='Create a temporary HTTPS ngrok URL')
    args=parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be between 1024 and 65535')
    try:
        import pyfiglet
        print(pyfiglet.figlet_format('TRACK-EM'))
    except ImportError:
        print('GHOST-EM')
    print('Made by GHO$T. GEOLOCATE PHONES VIA URL.')
    from wsgiref.simple_server import make_server, WSGIRequestHandler
    
    class QuietHandler(WSGIRequestHandler):
        def log_message(self,format,*args):
            pass
    try:
        server=make_server('127.0.0.1',args.port,application,handler_class=QuietHandler)
    except OSError as exc:
        print(f'Cannot bind port {args.port}: {exc}',file=sys.stderr);return 1
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    print(f'Local URL: http://127.0.0.1:{args.port}')
    tunnel=None
    if args.tunnel:
        try:
            from pyngrok import ngrok
            tunnel=ngrok.connect(addr=args.port,proto='http',bind_tls=True)
            print('Temporary public URL:',tunnel.public_url)
        except Exception as exc:
            print(f'Unable to open ngrok tunnel: {exc}',file=sys.stderr)
            server.shutdown();return 1
    print('Waiting for voluntarily shared coordinates. Press Ctrl+C to exit.')
    try:
        while True:
            try:lat,lon=EVENTS.get(timeout=0.5)
            except Empty:continue
            print(f'\nLocation received at {datetime.now(timezone.utc).isoformat()}')
            print(f'Latitude: {lat}\nLongitude: {lon}')
            print(f'Google Maps: https://www.google.com/maps/search/?api=1&query={lat},{lon}')
    except KeyboardInterrupt:
        print('\nShutting down…')
    finally:
        if tunnel is not None:
            try:ngrok.disconnect(tunnel.public_url)
            except Exception:pass
        server.shutdown();server.server_close()
    return 0

if __name__=='__main__':
    raise SystemExit(main())
