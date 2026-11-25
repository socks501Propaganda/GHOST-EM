import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SECRET_KEY"] = "local-admin-test-key"
os.environ.pop("DATABASE_URL", None)
app = importlib.import_module("GHOST-EM")

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client

settings.DATABASES["default"]["NAME"] = ":memory:"
call_command("check")
call_command("migrate", verbosity=0)
with connection.cursor() as cursor:
    cursor.execute("ATTACH DATABASE ':memory:' AS public")
    cursor.execute("""
        CREATE TABLE public.request_rate_limits (
            client_key TEXT, window_start INTEGER, request_count INTEGER,
            PRIMARY KEY (client_key, window_start)
        )
    """)

users = get_user_model()
admin_password = "Local-Test-Admin-Password-8"
member_password = "Local-Test-Member-Password-3"
operator = users.objects.create_superuser("operator", password=admin_password)
member = users.objects.create_user("candidate", password=member_password)
disabled = users.objects.create_user("disabled", is_active=False)
staff = users.objects.create_user("staff", is_staff=True)
path = f"/dashboard/accounts/{member.pk}/promote/"
admin = Client(enforce_csrf_checks=True, HTTP_HOST="localhost")
visitor = Client(HTTP_HOST="localhost")

def admin_get(target):
    return admin.get(target, secure=True)

def submit(password):
    return admin.post(path, {"password": password}, secure=True,
                      HTTP_REFERER="https://localhost" + path,
                      HTTP_X_CSRFTOKEN=admin.cookies["csrftoken"].value)

assert admin_get(path).status_code == 302
visitor.force_login(member)
assert visitor.get(path, secure=True).status_code == 302
assert visitor.post(path, {"password": admin_password}, secure=True).status_code == 302
admin.force_login(operator)
response = admin_get(path)
assert response.status_code == 200 and b"candidate" in response.content
assert response.headers["X-Frame-Options"] == "DENY"
assert response.headers["X-Content-Type-Options"] == "nosniff"
assert "no-store" in response.headers["Cache-Control"]
assert admin.post(path, {"password": admin_password}, secure=True).status_code == 403
for user in [operator, disabled, staff]:
    assert admin_get(f"/dashboard/accounts/{user.pk}/promote/").status_code == 404

with patch.object(app.time, "time", return_value=1800000000):
    for _ in range(5):
        assert b"password was incorrect" in submit("incorrect").content
    assert submit(admin_password).status_code == 429
member.refresh_from_db()
assert not member.is_superuser

with patch.object(app.time, "time", return_value=1800000060):
    response = submit(admin_password)
    assert response.status_code == 302 and response.url == "/dashboard/accounts/"
member.refresh_from_db()
assert member.is_superuser and member.is_staff
assert visitor.get("/dashboard/accounts/", secure=True).status_code == 302
assert visitor.login(username="candidate", password=member_password)
assert visitor.get("/dashboard/accounts/", secure=True).status_code == 200
assert admin_get(path).status_code == 404
assert "no-store" in admin_get("/dashboard/login/").headers["Cache-Control"]
print("Admin security and promotion integration checks passed.")
