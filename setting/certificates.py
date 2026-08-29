from pathlib import Path

from django.conf import settings


CERT_DIR = Path(settings.BASE_DIR) / "nginx" / "certs"

CERTIFICATE_FILE = CERT_DIR / "server.crt"
PRIVATE_KEY_FILE = CERT_DIR / "server.key"


def ensure_certificate_directory():

    CERT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def save_certificate(uploaded_file):

    ensure_certificate_directory()

    with open(
        CERTIFICATE_FILE,
        "wb",
    ) as destination:

        for chunk in uploaded_file.chunks():
            destination.write(chunk)


def save_private_key(uploaded_file):

    ensure_certificate_directory()

    with open(
        PRIVATE_KEY_FILE,
        "wb",
    ) as destination:

        for chunk in uploaded_file.chunks():
            destination.write(chunk)


def delete_certificate():

    if CERTIFICATE_FILE.exists():
        CERTIFICATE_FILE.unlink()


def delete_private_key():

    if PRIVATE_KEY_FILE.exists():
        PRIVATE_KEY_FILE.unlink()