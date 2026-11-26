import math

from django.db import migrations


def remove_duplicate_receptions(apps, schema_editor):
    survey_map = apps.get_model("rf_surveys", "SurveyMap")
    records = survey_map.objects.using(schema_editor.connection.alias)
    removed = 0
    for survey in records.select_for_update().iterator(chunk_size=100):
        seen = set()
        unique = []
        for row in survey.observations:
            details = dict(row["details"])
            address = details.get("BSSID", "").strip().lower()
            if address:
                kind = "BLE" if details.get("Type", "").strip().upper() == "BLE" else "WIFI"
                rounded = tuple(math.floor(row[key] * 10000 + .5) for key in ("lat", "lon"))
                key = kind, address, rounded
            else:
                key = row["lat"], row["lon"], tuple(sorted(details.items()))
            if key not in seen:
                unique.append(row)
                seen.add(key)
        removed += len(survey.observations) - len(unique)
        if len(unique) != len(survey.observations):
            survey.observations = unique
            survey.save(update_fields=["observations"], using=schema_editor.connection.alias)
    print(f"Removed {removed} duplicate survey observations.", flush=True)


class Migration(migrations.Migration):
    dependencies = [("rf_surveys", "0001_initial")]
    operations = [migrations.RunPython(remove_duplicate_receptions)]
