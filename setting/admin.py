from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.mail import EmailMessage
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse

import requests

from .models import (
    Update,
    MailSettings,
    SSLCertificateAdminProxy,
    HolidaySettings,
    GeneralSettings,
)

from .services import check_for_update, request_update, get_install_status

from .forms import (
    MailSettingsForm,
    CertificateUploadForm,
)

from .certificates import (
    CERTIFICATE_FILE,
    PRIVATE_KEY_FILE,
    delete_certificate,
    delete_private_key,
    save_certificate,
    save_private_key,
)


# ============================================================
# SOFTWARE UPDATE
# ============================================================

@admin.register(Update)
class UpdateAdmin(admin.ModelAdmin):

    change_list_template = (
        "admin/setting/update/change_list.html"
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def get_urls(self):

        urls = super().get_urls()

        custom_urls = [

            path(
                "check/",
                self.admin_site.admin_view(
                    self.check_update_view
                ),
                name="setting_update_check",
            ),

            path(
                "install/",
                self.admin_site.admin_view(
                    self.install_update_view
                ),
                name="setting_update_install",
            ),
        ]

        return custom_urls + urls

    def changelist_view(
        self,
        request,
        extra_context=None,
    ):

        update, created = (
            Update.objects.get_or_create(
                pk=1,
            )
        )

        try:
            install_status = get_install_status()
        except requests.RequestException:
            install_status = {"status": "unreachable"}

        context = {
            **self.admin_site.each_context(request),

            "title": _("Software Updates"),

            "update": update,

            "install_status": install_status,

            "check_url": reverse(
                "admin:setting_update_check"
            ),

            "install_url": reverse(
                "admin:setting_update_install"
            ),
        }

        return render(
            request,
            "admin/setting/update/change_list.html",
            context,
        )

    def check_update_view(self, request):

        try:

            result = check_for_update()

            Update.objects.update_or_create(
                pk=1,
                defaults={
                    "current_version": (
                        result["current_version"]
                    ),
                    "latest_version": (
                        result["latest_version"]
                    ),
                    "update_available": (
                        result["update_available"]
                    ),
                    "release_name": (
                        result["release_name"]
                    ),
                    "release_url": (
                        result["release_url"]
                    ),
                    "release_notes": (
                        result["release_notes"]
                    ),
                    "checked_at": timezone.now(),
                    "error_message": (
                        result["error_message"]
                    ),
                },
            )

            if result["update_available"]:

                self.message_user(
                    request,
                    _(
                        "Update verfügbar: "
                        "%(version)s"
                    ) % {
                        "version": (
                            result["latest_version"]
                        ),
                    },
                    level=messages.SUCCESS,
                )

            else:

                self.message_user(
                    request,
                    _(
                        "Du verwendest bereits die "
                        "aktuelle Version "
                        "%(version)s."
                    ) % {
                        "version": (
                            result["current_version"]
                        ),
                    },
                    level=messages.SUCCESS,
                )

        except Exception as exc:

            Update.objects.update_or_create(
                pk=1,
                defaults={
                    "checked_at": timezone.now(),
                    "error_message": str(exc),
                },
            )

            self.message_user(
                request,
                _(
                    "Fehler bei der Updateprüfung: "
                    "%(error)s"
                ) % {
                    "error": exc,
                },
                level=messages.ERROR,
            )

        return redirect(
            "admin:setting_update_changelist"
        )

    def install_update_view(self, request):

        update = Update.objects.filter(
            pk=1
        ).first()

        if not update:

            self.message_user(
                request,
                _(
                    "Es wurde noch keine "
                    "Updateprüfung durchgeführt."
                ),
                level=messages.ERROR,
            )

            return redirect(
                "admin:setting_update_changelist"
            )

        if not update.update_available:

            self.message_user(
                request,
                _("Es ist kein Update verfügbar."),
                level=messages.WARNING,
            )

            return redirect(
                "admin:setting_update_changelist"
            )

        try:

            version = request_update(
                update.latest_version
            )

            self.message_user(
                request,
                _(
                    "Update auf %(version)s "
                    "wurde gestartet."
                ) % {
                    "version": version,
                },
                level=messages.SUCCESS,
            )

        except requests.RequestException as exc:

            self.message_user(
                request,
                _(
                    "Updater nicht erreichbar: "
                    "%(error)s"
                ) % {
                    "error": exc,
                },
                level=messages.ERROR,
            )

        except Exception as exc:

            self.message_user(
                request,
                _(
                    "Update konnte nicht gestartet "
                    "werden: %(error)s"
                ) % {
                    "error": exc,
                },
                level=messages.ERROR,
            )

        return redirect(
            "admin:setting_update_changelist"
        )


# ============================================================
# MAIL SETTINGS
# ============================================================

@admin.register(MailSettings)
class MailSettingsAdmin(admin.ModelAdmin):

    form = MailSettingsForm

    list_display = (
        "enabled",
        "backend",
        "email_host",
        "email_port",
        "default_from_email",
        "updated_at",
    )

    fieldsets = (
        (
            _("E-Mail-Versand"),
            {
                "fields": (
                    "enabled",
                ),
                "description": _(
                    "Wenn der E-Mail-Versand deaktiviert "
                    "ist, werden keine E-Mails versendet "
                    "und auch keine E-Mails in der Konsole "
                    "ausgegeben."
                ),
            },
        ),
        (
            _("Backend"),
            {
                "fields": (
                    "backend",
                ),
            },
        ),
        (
            _("SMTP-Einstellungen"),
            {
                "fields": (
                    "email_host",
                    "email_port",
                    "email_host_user",
                    "email_host_password",
                    "email_use_tls",
                    "email_use_ssl",
                ),
            },
        ),
        (
            _("Absender"),
            {
                "fields": (
                    "default_from_email",
                ),
            },
        ),
        (
            _("Informationen"),
            {
                "fields": (
                    "updated_at",
                ),
            },
        ),
    )

    readonly_fields = (
        "updated_at",
    )

    def has_add_permission(self, request):

        return not MailSettings.objects.exists()

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return True


# ============================================================
# SSL-ZERTIFIKATE
# ============================================================

@admin.register(SSLCertificateAdminProxy)
class SSLCertificateAdmin(admin.ModelAdmin):

    def has_add_permission(self, request):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def changelist_view(
        self,
        request,
        extra_context=None,
    ):

        context = {
            **self.admin_site.each_context(request),

            "title": _("SSL-Zertifikate"),

            "certificate_exists": (
                CERTIFICATE_FILE.exists()
            ),

            "private_key_exists": (
                PRIVATE_KEY_FILE.exists()
            ),

            "certificate_size": (
                CERTIFICATE_FILE.stat().st_size
                if CERTIFICATE_FILE.exists()
                else None
            ),

            "private_key_size": (
                PRIVATE_KEY_FILE.stat().st_size
                if PRIVATE_KEY_FILE.exists()
                else None
            ),

            "upload_form": CertificateUploadForm(),
        }

        return TemplateResponse(
            request,
            "admin/setting/certificates.html",
            context,
        )

    def get_urls(self):

        urls = super().get_urls()

        custom_urls = [

            path(
                "upload/",
                self.admin_site.admin_view(
                    self.upload_certificate
                ),
                name="setting_certificates_upload",
            ),

            path(
                "delete-crt/",
                self.admin_site.admin_view(
                    self.delete_crt
                ),
                name="setting_certificates_delete_crt",
            ),

            path(
                "delete-key/",
                self.admin_site.admin_view(
                    self.delete_key
                ),
                name="setting_certificates_delete_key",
            ),

        ]

        return custom_urls + urls

    def upload_certificate(
        self,
        request,
    ):

        if request.method != "POST":

            return HttpResponseRedirect(
                reverse(
                    "admin:setting_sslcertificateadminproxy_changelist"
                )
            )

        form = CertificateUploadForm(
            request.POST,
            request.FILES,
        )

        if not form.is_valid():

            self.message_user(
                request,
                _(
                    "Die hochgeladenen Dateien "
                    "sind ungültig."
                ),
                messages.ERROR,
            )

            return HttpResponseRedirect(
                reverse(
                    "admin:setting_sslcertificateadminproxy_changelist"
                )
            )

        certificate = form.cleaned_data.get(
            "certificate"
        )

        private_key = form.cleaned_data.get(
            "private_key"
        )

        try:

            if certificate:
                save_certificate(
                    certificate
                )

            if private_key:
                save_private_key(
                    private_key
                )

            self.message_user(
                request,
                _(
                    "Zertifikate wurden erfolgreich "
                    "aktualisiert."
                ),
                messages.SUCCESS,
            )

        except Exception as error:

            self.message_user(
                request,
                _(
                    "Fehler beim Speichern: "
                    "%(error)s"
                ) % {
                    "error": error,
                },
                messages.ERROR,
            )

        return HttpResponseRedirect(
            reverse(
                "admin:setting_sslcertificateadminproxy_changelist"
            )
        )

    def delete_crt(
        self,
        request,
    ):

        if request.method == "POST":

            try:

                delete_certificate()

                self.message_user(
                    request,
                    _(
                        "server.crt wurde gelöscht."
                    ),
                    messages.SUCCESS,
                )

            except Exception as error:

                self.message_user(
                    request,
                    _(
                        "Fehler beim Löschen: "
                        "%(error)s"
                    ) % {
                        "error": error,
                    },
                    messages.ERROR,
                )

        return HttpResponseRedirect(
            reverse(
                "admin:setting_sslcertificateadminproxy_changelist"
            )
        )

    def delete_key(
        self,
        request,
    ):

        if request.method == "POST":

            try:

                delete_private_key()

                self.message_user(
                    request,
                    _(
                        "server.key wurde gelöscht."
                    ),
                    messages.SUCCESS,
                )

            except Exception as error:

                self.message_user(
                    request,
                    _(
                        "Fehler beim Löschen: "
                        "%(error)s"
                    ) % {
                        "error": error,
                    },
                    messages.ERROR,
                )

        return HttpResponseRedirect(
            reverse(
                "admin:setting_sslcertificateadminproxy_changelist"
            )
        )


# ============================================================
# HOLIDAY SETTINGS
# ============================================================

@admin.register(HolidaySettings)
class HolidaySettingsAdmin(admin.ModelAdmin):

    list_display = (
        "xml_feiertage_aktiv",
    )

    def has_add_permission(self, request):
        return not HolidaySettings.objects.exists()

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False


# ============================================================
# GENERAL SETTINGS
# ============================================================

@admin.register(GeneralSettings)
class GeneralSettingsAdmin(admin.ModelAdmin):

    fieldsets = (
        (
            _("Sprache"),
            {
                "fields": (
                    "language",
                ),
            },
        ),
        (
            _("Zeitzone"),
            {
                "fields": (
                    "timezone",
                    "automatic_dst",
                ),
            },
        ),
    )

    def has_add_permission(self, request):

        return not GeneralSettings.objects.exists()

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def changelist_view(
        self,
        request,
        extra_context=None,
    ):

        settings = GeneralSettings.get_solo()

        return redirect(
            "admin:setting_generalsettings_change",
            settings.pk,
        )