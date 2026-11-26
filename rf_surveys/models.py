from django.conf import settings
from django.db import models


class SurveyMap(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    observations = models.JSONField(default=list)
