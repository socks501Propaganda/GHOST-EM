from django.core.management import call_command
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder


def migrate_survey_storage():
    # The Render service starts Gunicorn directly. Serialize migration across
    # overlapping releases and workers, and skip it after the first rollout.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [426635218])
        applied = MigrationRecorder(connection).applied_migrations()
        if ("rf_surveys", "0002_remove_duplicate_receptions") not in applied:
            call_command("migrate", "rf_surveys", interactive=False)
