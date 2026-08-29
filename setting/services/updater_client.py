# services/updater_client.py
import requests
from django.conf import settings

def _headers():
    return {"X-Updater-Token": settings.UPDATER_SECRET}

def get_install_status() -> dict:
    resp = requests.get(f"{settings.UPDATER_URL}/status", headers=_headers(), timeout=5)
    resp.raise_for_status()
    return resp.json()

def trigger_install() -> dict:
    resp = requests.post(f"{settings.UPDATER_URL}/update", headers=_headers(), timeout=5)
    resp.raise_for_status()
    return resp.json()