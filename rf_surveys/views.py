import json
import math

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import SurveyMap


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_OBSERVATIONS = 10000
DETAIL_FIELDS = {
    "SSID", "BSSID", "Channel", "Frequency", "Security", "First seen",
    "Last seen", "Last updated", "Type", "GPS accuracy", "Signal",
}


def normalize(rows):
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_OBSERVATIONS:
        raise ValueError
    observations = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError
        lat, lon, details = row.get("lat"), row.get("lon"), row.get("details")
        if (type(lat) not in (int, float) or type(lon) not in (int, float)
                or not -90 <= lat < 90 or not -180 <= lon < 180
                or not math.isfinite(lat) or not math.isfinite(lon)
                or not isinstance(details, list) or len(details) > len(DETAIL_FIELDS)):
            raise ValueError
        fields = {}
        for item in details:
            if (not isinstance(item, list) or len(item) != 2
                    or not isinstance(item[0], str) or item[0] not in DETAIL_FIELDS
                    or not isinstance(item[1], str) or len(item[1]) > 360):
                raise ValueError
            fields[item[0]] = item[1]
        observations.append({"lat": float(lat), "lon": float(lon), "details": sorted(fields.items())})
    return observations


def observation_key(row):
    return (row["lat"], row["lon"], tuple(sorted(tuple(item) for item in row["details"])))


@never_cache
@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def survey_map(request):
    if request.headers.get("X-Ghost-Em-Owner") != str(request.user.pk):
        return JsonResponse({"error": "The signed-in account has changed. Reload the map."}, status=403)

    if request.method == "GET":
        rows = SurveyMap.objects.filter(owner=request.user).values_list("observations", flat=True).first()
        return JsonResponse({"observations": rows or []})

    if request.method == "DELETE":
        SurveyMap.objects.filter(owner=request.user).delete()
        return JsonResponse({"observations": []})

    try:
        size = int(request.META.get("CONTENT_LENGTH") or "0")
        if request.content_type != "application/json" or not 0 < size <= MAX_UPLOAD_BYTES:
            return JsonResponse({"error": "Survey upload is too large or invalid."}, status=400)
        rows = normalize(json.loads(request.body))
    except (ValueError, OverflowError, UnicodeError, RecursionError):
        return JsonResponse({"error": "Survey observations are invalid or exceed the upload limit."}, status=400)

    with transaction.atomic():
        survey, _ = SurveyMap.objects.select_for_update().get_or_create(owner=request.user)
        combined = {observation_key(row): row for row in survey.observations}
        for row in rows:
            combined[observation_key(row)] = row
        if len(combined) > MAX_OBSERVATIONS:
            return JsonResponse({"error": "Your map has reached its saved observation limit."}, status=409)
        survey.observations = list(combined.values())
        survey.save(update_fields=["observations"])
    return JsonResponse({"observations": survey.observations})
