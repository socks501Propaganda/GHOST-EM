#!/usr/bin/env python3
"""Consent-based geolocation teaching demo; local Django server + optional ngrok."""

import ipaddress
import argparse
import os
import hashlib
import hmac
import json
import time
import secrets
import signal
import sys
import threading
from datetime import datetime, timezone
from functools import wraps
from queue import Queue, Empty
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.management import execute_from_command_line
from django.http import HttpResponse, JsonResponse
from django.http.request import split_domain_port
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
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
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
        TEMPLATES=[
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(os.path.dirname(__file__), "templates")],
        "APP_DIRS": True,
        "OPTIONS": {},
    }
],
        SECURE_REFERRER_POLICY="strict-origin-when-cross-origin",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        CSRF_COOKIE_SECURE=True,
        CSRF_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_AGE=3600,
        AUTH_PASSWORD_VALIDATORS=[
            {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
            {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
            {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
            {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
        ],
        LOGIN_URL="login",
        TURNSTILE_REQUIRED=bool(render_host),
        TURNSTILE_SITE_KEY=os.environ.get("TURNSTILE_SITE_KEY", ""),
        TURNSTILE_SECRET_KEY=os.environ.get("TURNSTILE_SECRET_KEY", ""),
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    )
######

EVENTS = Queue()
TOKEN = secrets.token_urlsafe(24)

HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Darknet Dropspot</title><style>body{font:16px system-ui;max-width:540px;margin:10vh auto;padding:1.5rem;line-height:1.5}button{padding:.8rem 1.2rem;font-size:1rem}#status{white-space:pre-wrap}</style></head><body><h1>Quick Access</h1><p>This is the new portal for seeing where the next dead drop will be.</p><button id="share">Register for drop</button><p id="status" role="status"></p><script>
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
</script></body></html>"""


@ensure_csrf_cookie
@login_required
def index(request):
    return render(request, "new public ghostem.html")

@login_required
def rf_map(request):
    return render(request, "rf_map.html")


def count_request(scope, subject):
    from django.db import connection

    client_key = hmac.new(
        settings.SECRET_KEY.encode(),
        (scope + subject).encode(),
        hashlib.sha256,
    ).hexdigest()

    window_start = int(time.time()) // 60

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.request_rate_limits
                (client_key, window_start, request_count)
            VALUES (%s, %s, 1)
            ON CONFLICT (client_key, window_start)
            DO UPDATE SET
                request_count = request_rate_limits.request_count + 1
            RETURNING request_count
            """,
            [client_key, window_start],
        )
        count = cursor.fetchone()[0]

    return count


def check_rate_limit(request):
    try:
        client_ip = str(ipaddress.ip_address(request.META.get("REMOTE_ADDR", "")))
    except ValueError:
        return False
    return count_request("", client_ip) <= 5


def turnstile_passes(request, action):
    token = request.POST.get("cf-turnstile-response", "")
    if not token or len(token) > 2048:
        return False

    verification = Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=urlencode({"secret": settings.TURNSTILE_SECRET_KEY, "response": token}).encode(),
    )
    try:
        with urlopen(verification, timeout=4) as response:
            result = json.load(response)
    except (OSError, ValueError):
        return False
    return (
        isinstance(result, dict)
        and result.get("success") is True
        and result.get("action") == action
        and result.get("hostname") == split_domain_port(request.get_host())[0]
    )


def protect_login(action):
    def decorate(view):
        @csrf_protect
        @wraps(view)
        def protected(request, *args, **kwargs):
            if request.method == "POST":
                widget_enabled = bool(settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY)
                if widget_enabled:
                    if not turnstile_passes(request, action):
                        return HttpResponse("Verification failed. Go back and try again.", status=403)
                elif settings.TURNSTILE_REQUIRED or settings.TURNSTILE_SITE_KEY or settings.TURNSTILE_SECRET_KEY:
                    return HttpResponse("Sign-in verification is unavailable.", status=503)

                username = request.POST.get("username", "")[:150].casefold()
                if count_request("login:", username) > 8:
                    return HttpResponse(
                        "Too many sign-in attempts. Try again in a minute.",
                        status=429,
                        headers={"Retry-After": "60"},
                    )
            return view(request, *args, **kwargs)
        return protected
    return decorate


@csrf_protect
def submit(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)

    if not check_rate_limit(request):
        return JsonResponse(
            {"error": "Too many requests. Please wait a minute."},
            status=429,
        )

    try:
        payload = json.loads(request.body)
        lat = float(payload["latitude"])
        lon = float(payload["longitude"])

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid coordinates")

    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid coordinates"}, status=400)

    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.authorized_locations (latitude, longitude)
            VALUES (%s, %s)
            """,
            [lat, lon],
        )

    return JsonResponse({"ok": True})


from django.contrib.auth import authenticate, login
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.utils.html import escape


@require_http_methods(["GET", "POST"])
@protect_login("admin_login")
@ensure_csrf_cookie
def dashboard_login(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect("/dashboard/")

    error = ""
    widget = ""
    if settings.TURNSTILE_SITE_KEY:
        widget = f'<div class="cf-turnstile" data-sitekey="{escape(settings.TURNSTILE_SITE_KEY)}" data-action="admin_login"></div>'

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
    <head><meta charset="utf-8"><title>GHOST-EM Login</title>
    {"<script src='https://challenges.cloudflare.com/turnstile/v0/api.js' async defer></script>" if widget else ""}
    </head>
    <body>
      <h1>GHOST-EM Administrator Login</h1>
      {error}
      <form method="post">
        <input type="hidden" name="csrfmiddlewaretoken"
               value="{escape(get_token(request))}">
        <label>Username <input name="username" required></label>
        <label>Password <input type="password" name="password" required></label>
        {widget}
        <button type="submit">Sign in</button>
      </form>
    </body>
    </html>
    """)


##

from django.db import connection
from django.utils.html import escape


@user_passes_test(
    lambda user: user.is_authenticated and user.is_superuser,
    login_url="/dashboard/login/",
)
def dashboard(request):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM public.authorized_locations
            WHERE expires_at > NOW()
        """)
        count = cursor.fetchone()[0]
        cursor.execute("""
            SELECT latitude, longitude
            FROM public.authorized_locations
            WHERE expires_at > NOW()
            ORDER BY submitted_at DESC
            LIMIT 100
        """)
        locations = cursor.fetchall()
    return render(request, "dashboard.html", {
        "active_count": count,
        "locations": [{"lat": lat, "lng": lon} for lat, lon in locations],
    })

##

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone as django_timezone
from django.views.decorators.cache import never_cache


@never_cache
@user_passes_test(
    lambda user: user.is_authenticated and user.is_superuser,
    login_url="/dashboard/login/",
)
@require_http_methods(["GET", "POST"])
def dashboard_accounts(request):
    accounts = get_user_model().objects.filter(is_staff=False, is_superuser=False)
    form = UserCreationForm()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            form = UserCreationForm(request.POST)
            if form.is_valid():
                form.save()
                return redirect("dashboard_accounts")
        elif action in {"enable", "disable"}:
            account_id = request.POST.get("account_id", "")
            if not account_id.isascii() or not account_id.isdecimal() or len(account_id) > 10:
                return HttpResponse("Invalid account.", status=400)
            with transaction.atomic():
                if not accounts.filter(pk=int(account_id)).update(is_active=action == "enable"):
                    return HttpResponse("Account not found.", status=404)
                if action == "disable":
                    sessions = Session.objects.filter(expire_date__gt=django_timezone.now())
                    for session in sessions.iterator():
                        if session.get_decoded().get(SESSION_KEY) == str(int(account_id)):
                            session.delete()
            return redirect("dashboard_accounts")
        else:
            return HttpResponse("Invalid account action.", status=400)

    return render(
        request, "dashboard_accounts.html",
        {"form": form, "accounts": accounts.order_by("username")},
    )


urlpatterns = [
    path("", index),
    path(
        "login/",
        protect_login("login")(LoginView.as_view(
            template_name="login.html",
            next_page="/",
            redirect_authenticated_user=True,
            extra_context={"turnstile_site_key": settings.TURNSTILE_SITE_KEY},
        )),
        name="login",
    ),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("submit", submit),
    path("rf-map/", rf_map),
    path("dashboard/login/", dashboard_login),
    path("dashboard/accounts/", dashboard_accounts, name="dashboard_accounts"),
    path("dashboard/", dashboard),
]

def main():
    parser = argparse.ArgumentParser(
        description="Consent-based Track-Em educational demo"
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--tunnel", action="store_true", help="Create a temporary HTTPS ngrok URL"
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    try:
        import pyfiglet

        print(pyfiglet.figlet_format("GHO$T-EM"))
    except ImportError:
        print("GHOST-EM")
    print("MADE BY WE$-GHO$T. FUCK THE FEDS.")
    from wsgiref.simple_server import make_server, WSGIRequestHandler

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, format, *args):
            pass

    try:
        server = make_server(
            "127.0.0.1", args.port, application, handler_class=QuietHandler
        )
    except OSError as exc:
        print(f"Cannot bind port {args.port}: {exc}", file=sys.stderr)
        return 1
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Local URL: http://127.0.0.1:{args.port}")
    tunnel = None
    if args.tunnel:
        try:
            from pyngrok import ngrok

            tunnel = ngrok.connect(addr=args.port, proto="http", bind_tls=True)
            print("Temporary public URL:", tunnel.public_url)
        except Exception as exc:
            print(f"Unable to open ngrok tunnel: {exc}", file=sys.stderr)
            server.shutdown()
            return 1
    print("Waiting for voluntarily shared coordinates. Press Ctrl+C to exit.")
    try:
        while True:
            try:
                lat, lon = EVENTS.get(timeout=0.5)
            except Empty:
                continue
            print(f"\nLocation received at {datetime.now(timezone.utc).isoformat()}")
            print(f"Latitude: {lat}\nLongitude: {lon}")
            print(
                f"Google Maps: https://www.google.com/maps/search/?api=1&query={lat},{lon}"
            )
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        if tunnel is not None:
            try:
                ngrok.disconnect(tunnel.public_url)
            except Exception:
                pass
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
