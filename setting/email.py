from django.core.mail import EmailMessage, get_connection

from .models import MailSettings


def get_mail_settings():
    """
    Lädt die aktuelle E-Mail-Konfiguration.
    """

    return MailSettings.objects.first()


def get_mail_connection():
    """
    Erstellt eine Django-Mail-Connection
    anhand der Einstellungen aus der Datenbank.
    """

    mail_settings = get_mail_settings()

    if mail_settings is None:
        raise RuntimeError(
            "Es wurden noch keine E-Mail-Einstellungen "
            "im Django-Admin eingerichtet."
        )

    if mail_settings.backend == MailSettings.BACKEND_CONSOLE:

        return get_connection(
            backend=MailSettings.BACKEND_CONSOLE,
        )

    return get_connection(
        backend=MailSettings.BACKEND_SMTP,
        host=mail_settings.email_host,
        port=mail_settings.email_port,
        username=mail_settings.email_host_user,
        password=mail_settings.email_host_password,
        use_tls=mail_settings.email_use_tls,
        use_ssl=mail_settings.email_use_ssl,
    )


def get_default_from_email():
    """
    Gibt die konfigurierte Absenderadresse zurück.
    """

    mail_settings = get_mail_settings()

    if mail_settings is None:
        return None

    return mail_settings.default_from_email


def send_configured_mail(
    subject,
    message,
    recipient_list,
    from_email=None,
    fail_silently=False,
):
    """
    Versendet eine E-Mail mit der Datenbank-Konfiguration.
    """

    if from_email is None:
        from_email = get_default_from_email()

    if not from_email:
        raise RuntimeError(
            "Es wurde keine Standard-Absenderadresse "
            "im Django-Admin eingerichtet."
        )

    connection = get_mail_connection()

    email = EmailMessage(
        subject=subject,
        body=message,
        from_email=from_email,
        to=recipient_list,
        connection=connection,
    )

    return email.send(
        fail_silently=fail_silently
    )
