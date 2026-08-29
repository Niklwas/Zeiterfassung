import requests

from version import VERSION


GITHUB_OWNER = "Niklwas"
GITHUB_REPO = "Zeiterfassung"

GITHUB_API_URL = (
    f"https://api.github.com/repos/"
    f"{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)


def check_for_update():
    """
    Prüft das neueste GitHub Release und vergleicht es
    mit der aktuell installierten Version.
    """

    current_version = VERSION

    try:
        response = requests.get(
            GITHUB_API_URL,
            timeout=10,
            headers={
                "Accept": "application/vnd.github+json",
            },
        )

        # Kein Release vorhanden
        if response.status_code == 404:
            return {
                "current_version": current_version,
                "latest_version": "",
                "update_available": False,
                "release_name": "",
                "release_url": "",
                "release_notes": "",
                "error_message": (
                    "Auf GitHub wurde noch kein Release veröffentlicht."
                ),
            }

        response.raise_for_status()

        release = response.json()

        tag_name = release.get("tag_name", "")

        # "v1.0.260827" -> "1.0.260827"
        latest_version = tag_name.removeprefix("v")

        return {
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": latest_version != current_version,
            "release_name": release.get("name", ""),
            "release_url": release.get("html_url", ""),
            "release_notes": release.get("body", ""),
            "error_message": "",
        }

    except requests.RequestException as exc:
        return {
            "current_version": current_version,
            "latest_version": "",
            "update_available": False,
            "release_name": "",
            "release_url": "",
            "release_notes": "",
            "error_message": (
                f"GitHub konnte nicht erreicht werden: {exc}"
            ),
        }


def request_update(version):
    """
    Erstellt einen Update-Auftrag für den Host-Updater.
    """

    version = version.strip()

    if not version:
        raise ValueError("Keine Version angegeben.")

    # Sicherheit:
    # Es werden nur Versionsnummern bzw. vVersionsnummern akzeptiert.
    if not version.startswith("v"):
        version = f"v{version}"

    # Nur einfache Versions-Tags erlauben.
    # Beispiel:
    # v1.0.260827
    import re

    if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise ValueError(
            f"Ungültige Versionsnummer: {version}"
        )

    UPDATE_REQUEST_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    UPDATE_REQUEST_FILE.write_text(
        version,
        encoding="utf-8",
    )

    return version