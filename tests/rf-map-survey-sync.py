import importlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SECRET_KEY"] = "local-survey-sync-test-key"
os.environ.pop("DATABASE_URL", None)
importlib.import_module("GHOST-EM")

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

settings.DATABASES["default"]["NAME"] = ":memory:"
call_command("migrate", verbosity=0)

url = "/rf-map/synced-survey/"
host = {"HTTP_HOST": "localhost"}
users = get_user_model()
alice = users.objects.create_user("alice")
bob = users.objects.create_user("bob")
phone = Client(enforce_csrf_checks=True, **host)
desktop = Client(**host)
other = Client(**host)
guest = Client(**host)
phone.force_login(alice)
desktop.force_login(alice)
other.force_login(bob)
assert guest.get(url, secure=True).status_code == 302
assert b"surveySyncStatus" not in guest.get("/rf-map/guest/", secure=True).content.split(b"<script", 1)[0]
assert b'id="surveySyncStatus"' not in phone.get("/rf-map/guest/", secure=True).content
phone.get("/rf-map/", secure=True)
csrf = {
    "HTTP_REFERER": "https://localhost/rf-map/",
    "HTTP_X_CSRFTOKEN": phone.cookies["csrftoken"].value,
}
owner = {"HTTP_X_GHOST_EM_OWNER": str(alice.pk)}
row = {"lat": 42, "lon": -76, "details": [["SSID", "Example"], ["Signal", "-60"]]}

def upload(rows, **headers):
    return phone.post(url, json.dumps(rows), content_type="application/json",
                      secure=True, **owner, **headers)

assert upload([row]).status_code == 403
assert upload([{**row, "lat": 95}], **csrf).status_code == 400
assert upload([row], **csrf).status_code == 200
assert upload([row], **csrf).status_code == 200
assert upload([{**row, "lon": -77}], **csrf).status_code == 200
assert len(desktop.get(url, secure=True, **owner).json()["observations"]) == 2
assert other.get(url, secure=True, **owner).status_code == 403
assert other.get(url, secure=True, HTTP_X_GHOST_EM_OWNER=str(bob.pk)).json()["observations"] == []
assert phone.delete(url, secure=True, **owner, **csrf).status_code == 200
assert desktop.get(url, secure=True, **owner).json()["observations"] == []
print("Survey sync passed location validation, two-device visibility, retry deduplication, account isolation and deletion.")
uplink = "/rf-map/survey-uplink/"
assert guest.get(uplink, secure=True).status_code == 401
auth = phone.get(uplink, secure=True)
assert auth.json()["owner"] == str(alice.pk)
assert auth.json()["username"] == "alice"
uplink_headers = {
    **owner,
    "HTTP_ORIGIN": "https://localhost",
    "HTTP_X_CSRFTOKEN": auth.json()["csrfToken"],
}
csv_header = "SSID,MAC,Frequency,AuthMode,FirstSeen,LastSeen,CurrentLatitude,CurrentLongitude,AccuracyMeters,RSSI,Type\n"
csv_text = csv_header + '"Café, plaza",02:00:00:00:00:01,2412,WPA2,,,42,-76,5,-60,WIFI\n'
csv_text += "Untagged,02:00:00:00:00:02,2412,WPA2,,,,,,-80,WIFI\n"
def submit_csv(client, data, headers):
    return client.post(uplink, data.encode("utf-8"), content_type="text/csv", secure=True, **headers)

assert submit_csv(phone, csv_text, owner).status_code == 403
assert submit_csv(phone, csv_text, {**uplink_headers, "HTTP_X_GHOST_EM_OWNER": str(bob.pk)}).status_code == 403
assert submit_csv(phone, csv_header, uplink_headers).status_code == 400
assert submit_csv(phone, csv_text, uplink_headers).json() == {"count": 1}
assert submit_csv(phone, csv_text, uplink_headers).json() == {"count": 1}
saved = desktop.get(url, secure=True, **owner).json()["observations"]
assert len(saved) == 1 and ["SSID", "Café, plaza"] in saved[0]["details"]
assert upload(saved, **csrf).status_code == 200
assert len(desktop.get(url, secure=True, **owner).json()["observations"]) == 1
assert other.get(url, secure=True, HTTP_X_GHOST_EM_OWNER=str(bob.pk)).json()["observations"] == []
print("Android uplink passed authentication, CSRF, account binding, quoted UTF-8 CSV, and repeat deduplication.")
