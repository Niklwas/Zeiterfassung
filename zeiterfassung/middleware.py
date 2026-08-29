from django.utils import translation

from setting.models import GeneralSettings


class GeneralSettingsLanguageMiddleware:
    """
    Aktiviert die in GeneralSettings gespeicherte Sprache
    für die gesamte Anwendung.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        try:
            settings = GeneralSettings.get_solo()
            language = settings.language

        except Exception:
            # Falls die Datenbank noch nicht verfügbar ist,
            # verwendet Django seine Standardsprache.
            language = None

        if language:
            translation.activate(language)
            request.LANGUAGE_CODE = language

        response = self.get_response(request)

        return response