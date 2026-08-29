from django import forms

from .models import MailSettings


class MailSettingsForm(forms.ModelForm):

    class Meta:
        model = MailSettings
        fields = "__all__"

        widgets = {
            "email_host_password": forms.PasswordInput(
                render_value=True
            ),
        }

    def clean(self):

        cleaned_data = super().clean()

        backend = cleaned_data.get("backend")
        use_tls = cleaned_data.get("email_use_tls")
        use_ssl = cleaned_data.get("email_use_ssl")

        if backend == MailSettings.BACKEND_SMTP:

            if use_tls and use_ssl:
                raise forms.ValidationError(
                    "TLS und SSL können nicht gleichzeitig "
                    "aktiviert werden."
                )

        return cleaned_data



class CertificateUploadForm(forms.Form):

    certificate = forms.FileField(
        label="Zertifikat (.crt)",
        required=False,
    )

    private_key = forms.FileField(
        label="Privater Schlüssel (.key)",
        required=False,
    )

    def clean_certificate(self):

        certificate = self.cleaned_data.get("certificate")

        if certificate:
            if not certificate.name.lower().endswith(".crt"):
                raise forms.ValidationError(
                    "Das Zertifikat muss eine .crt-Datei sein."
                )

        return certificate

    def clean_private_key(self):

        private_key = self.cleaned_data.get("private_key")

        if private_key:
            if not private_key.name.lower().endswith(".key"):
                raise forms.ValidationError(
                    "Der private Schlüssel muss eine .key-Datei sein."
                )

        return private_key

