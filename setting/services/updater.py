# settings/services/updater.py
import requests
from django.conf import settings
from packaging.version import Version, InvalidVersion

GITHUB_REPO = "Niklwas/Zeiterfassung"


def _get_installed_version() -> str:
    """Liest die installierte Versionsnummer aus /app/version.py."""
    try:
        namespace = {}

        with open("/app/version.py", encoding="utf-8") as f:
            exec(f.read(), namespace)

        version = namespace.get("VERSION", "")

        if not version:
            return "unbekannt"

        return str(version).strip().lstrip("v")

    except (FileNotFoundError, OSError, SyntaxError):
        return "unbekannt"


def check_for_update() -> dict:
    """
    Fragt die GitHub-Releases-API ab und gibt ein dict zurück,
    das direkt in das Update-Model passt.
    """
    result = {
        "current_version": _get_installed_version(),
        "latest_version": "",
        "update_available": False,
        "release_name": "",
        "release_url": "",
        "release_notes": "",
        "error_message": "",
    }

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=10,
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        data = resp.json()

        latest_tag = data["tag_name"].lstrip("v")
        current = result["current_version"]

        try:
            is_newer = Version(latest_tag) > Version(current)
        except InvalidVersion:
            is_newer = latest_tag != current

        result.update({
            "latest_version": latest_tag,
            "update_available": is_newer,
            "release_name": data.get("name", ""),
            "release_url": data.get("html_url", ""),
            "release_notes": data.get("body", ""),
        })

    except requests.RequestException as e:
        result["error_message"] = str(e)

    return result


# ------------------------------------------------------------------
# Kommunikation mit dem Sidecar-Updater-Container (Docker-Socket-Zugriff)
# ------------------------------------------------------------------

def _updater_headers() -> dict:
    return {
        "X-Updater-Secret": settings.UPDATER_SECRET
    }

def get_install_status() -> dict:
    """Fragt beim Sidecar den aktuellen Installationsstatus ab."""
    resp = requests.get(
        f"{settings.UPDATER_URL}/status",
        headers=_updater_headers(),
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def request_update(latest_version: str = "") -> str:
    """
    Löst das Update im Sidecar-Updater aus.
    """

    if not latest_version:
        raise ValueError("Keine Update-Version angegeben.")

    version = latest_version.strip()

    if not version.startswith("v"):
        version = f"v{version}"

    resp = requests.post(
        f"{settings.UPDATER_URL}/update",
        headers=_updater_headers(),
        json={
            "version": version,
        },
        timeout=5,
    )

    resp.raise_for_status()

    return version