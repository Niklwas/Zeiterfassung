from django.utils import timezone
from zoneinfo import ZoneInfo

from .models import GeneralSettings


class GeneralSettingsTimezoneMiddleware:
    """
    Aktiviert die in GeneralSettings konfigurierte Zeitzone
    für die aktuelle Django-Anfrage.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        settings_obj = GeneralSettings.objects.first()

        if settings_obj and settings_obj.timezone:

            try:
                tz = ZoneInfo(settings_obj.timezone)
                timezone.activate(tz)

            except Exception:
                timezone.deactivate()

        else:
            timezone.deactivate()

        response = self.get_response(request)

        timezone.deactivate()

        return response