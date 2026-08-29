from django.db import models
from django.utils.translation import gettext_lazy as _
from zoneinfo import available_timezones


# ============================================================
# SOFTWARE UPDATE
# ============================================================

class Update(models.Model):

    current_version = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Aktuelle Version"),
    )

    latest_version = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Neueste Version"),
    )

    release_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Release"),
    )

    release_url = models.URLField(
        blank=True,
        verbose_name=_("Release-URL"),
    )

    release_notes = models.TextField(
        blank=True,
        verbose_name=_("Release Notes"),
    )

    checked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Geprüft am"),
    )

    update_available = models.BooleanField(
        default=False,
        verbose_name=_("Update verfügbar"),
    )

    error_message = models.TextField(
        blank=True,
        verbose_name=_("Fehlermeldung"),
    )

    class Meta:
        verbose_name = _("Software-Update")
        verbose_name_plural = _("Software-Updates")

    def __str__(self):
        return f"Update-Status ({self.current_version})"


# ============================================================
# MAIL SETTINGS
# ============================================================

class MailSettings(models.Model):

    BACKEND_SMTP = "django.core.mail.backends.smtp.EmailBackend"
    BACKEND_CONSOLE = "django.core.mail.backends.console.EmailBackend"

    BACKEND_CHOICES = [
        (
            BACKEND_SMTP,
            _("SMTP EmailBackend"),
        ),
        (
            BACKEND_CONSOLE,
            _("Console EmailBackend"),
        ),
    ]

    enabled = models.BooleanField(
        default=True,
        verbose_name=_("E-Mail-Versand aktiviert"),
        help_text=_(
            "Wenn deaktiviert, werden keine E-Mails "
            "versendet und auch keine E-Mails in der "
            "Konsole ausgegeben."
        ),
    )

    backend = models.CharField(
        max_length=255,
        choices=BACKEND_CHOICES,
        default=BACKEND_CONSOLE,
        verbose_name=_("E-Mail-Backend"),
    )

    email_host = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("E-Mail-Host"),
    )

    email_port = models.PositiveIntegerField(
        default=587,
        verbose_name=_("E-Mail-Port"),
    )

    email_host_user = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("E-Mail-Benutzer"),
    )

    email_host_password = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name=_("E-Mail-Passwort"),
    )

    email_use_tls = models.BooleanField(
        default=True,
        verbose_name=_("TLS verwenden"),
    )

    email_use_ssl = models.BooleanField(
        default=False,
        verbose_name=_("SSL verwenden"),
    )

    default_from_email = models.EmailField(
        blank=True,
        default="noreply@zeiterfassung.local",
        verbose_name=_("Standard-Absender"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Zuletzt geändert"),
    )

    class Meta:
        verbose_name = _("E-Mail-Einstellung")
        verbose_name_plural = _("E-Mail-Einstellungen")

    def __str__(self):
        return str(_("E-Mail-Einstellungen"))


# ============================================================
# SSL CERTIFICATE
# ============================================================

class SSLCertificateAdminProxy(models.Model):

    class Meta:
        managed = False
        verbose_name = _("SSL-Zertifikat")
        verbose_name_plural = _("SSL-Zertifikate")


# ============================================================
# HOLIDAY SETTINGS
# ============================================================

class HolidaySettings(models.Model):

    xml_feiertage_aktiv = models.BooleanField(
        default=True,
        verbose_name=_("XML-Feiertage aktiv"),
        help_text=_(
            "Wenn deaktiviert, werden Feiertage aus "
            "den XML-Dateien ignoriert."
        ),
    )

    class Meta:
        verbose_name = _("Feiertagseinstellung")
        verbose_name_plural = _("Feiertagseinstellungen")

    def __str__(self):
        return str(_("Feiertagseinstellungen"))


# ============================================================
# GENERAL SETTINGS
# ============================================================

class GeneralSettings(models.Model):

    LANGUAGE_CHOICES = [
        ("de", _("Deutsch")),
        ("en", _("English")),
    ]

    # ========================================================
    # LANGUAGE
    # ========================================================

    language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default="de",
        verbose_name=_("Sprache"),
    )

    # ========================================================
    # TIMEZONE
    # ========================================================

    timezone = models.CharField(
        max_length=100,
        choices=[
            (tz, tz)
            for tz in sorted(available_timezones())
        ],
        default="Europe/Berlin",
        verbose_name=_("Zeitzone"),
        help_text=_(
            "Die Zeitzone der Anwendung."
        ),
    )

    # ========================================================
    # AUTOMATIC DAYLIGHT SAVING TIME
    # ========================================================

    automatic_dst = models.BooleanField(
        default=True,
        verbose_name=_(
            "Automatische Sommer-/Winterzeit"
        ),
        help_text=_(
            "Wenn aktiviert, wird die Sommer- und "
            "Winterzeit automatisch anhand der "
            "gewählten Zeitzone berücksichtigt."
        ),
    )

    # ========================================================
    # META
    # ========================================================

    class Meta:
        verbose_name = _("Allgemeine Einstellung")
        verbose_name_plural = _("Allgemeine Einstellungen")

    def __str__(self):
        return "General Settings"

    # ========================================================
    # SINGLETON
    # ========================================================

    def save(self, *args, **kwargs):

        self.pk = 1

        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):

        obj, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                "language": "de",
                "timezone": "Europe/Berlin",
                "automatic_dst": True,
            },
        )

        return obj