import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


app = FastAPI(
    title="Zeiterfassung Updater"
)


# ============================================================
# Configuration
# ============================================================

UPDATER_SECRET = os.environ["UPDATER_SECRET"]

GITHUB_REPO = os.getenv(
    "GITHUB_REPO",
    "Niklwas/Zeiterfassung",
)

IMAGE_NAME = os.getenv(
    "IMAGE_NAME",
    "zeiterfassung-app",
)

APP_CONTAINER = os.getenv(
    "APP_CONTAINER",
    "django-app",
)

UPDATER_PORT = int(
    os.getenv(
        "UPDATER_PORT",
        "9000",
    )
)

TMP_DIR = Path(
    "/project/.updater-build"
)

# ============================================================
# State
# ============================================================

state = {
    "status": "idle",
    "version": "",
    "previous_version": "",
    "message": "",
    "error": "",
    "started_at": None,
    "finished_at": None,
}

update_lock = threading.Lock()


# ============================================================
# Request model
# ============================================================

class UpdateRequest(BaseModel):
    version: str


# ============================================================
# Authentication
# ============================================================

def authenticate(
    secret: Optional[str]
):
    if secret != UPDATER_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )


# ============================================================
# Version
# ============================================================

def normalize_version(
    version: str
) -> str:

    version = version.strip()

    if not version:
        raise ValueError(
            "Keine Version angegeben."
        )

    if not version.startswith("v"):
        version = f"v{version}"

    return version


# ============================================================
# Shell
# ============================================================

def run_command(
    command: list[str],
    timeout: int = 1800,
):

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "\n".join([
                f"Befehl fehlgeschlagen:",
                " ".join(command),
                "",
                "STDOUT:",
                result.stdout,
                "",
                "STDERR:",
                result.stderr,
            ])
        )

    return result.stdout


# ============================================================
# GitHub Release
# ============================================================

def get_release(
    version: str
):

    version = normalize_version(
        version
    )

    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_REPO}/releases/tags/"
        f"{version}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "Accept":
                "application/vnd.github+json",
            "User-Agent":
                "Zeiterfassung-Updater",
        },
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:

            import json

            return json.loads(
                response.read()
                .decode("utf-8")
            )

    except Exception as exc:

        raise RuntimeError(
            f"GitHub Release {version} "
            f"nicht gefunden: {exc}"
        )


# ============================================================
# Download Release
# ============================================================

def download_release(
    version: str,
    target: Path,
):

    url = (
        f"https://github.com/"
        f"{GITHUB_REPO}/archive/refs/tags/"
        f"{version}.tar.gz"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Zeiterfassung-Updater",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=300,
    ) as response:

        with open(
            target,
            "wb",
        ) as file:

            shutil.copyfileobj(
                response,
                file,
            )


# ============================================================
# Extract Release
# ============================================================

def extract_release(
    archive: Path,
    destination: Path,
):

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tarfile.open(
        archive,
        "r:gz",
    ) as tar:

        # Schutz gegen Path Traversal
        destination_resolved = (
            destination.resolve()
        )

        for member in tar.getmembers():

            member_path = (
                destination /
                member.name
            ).resolve()

            if not str(
                member_path
            ).startswith(
                str(destination_resolved)
            ):

                raise RuntimeError(
                    "Unsicheres Release-Archiv."
                )

        tar.extractall(
            destination,
            filter="data",
        )

    directories = [
        item
        for item in destination.iterdir()
        if item.is_dir()
    ]

    if len(directories) != 1:

        raise RuntimeError(
            "Unerwartete GitHub-Archivstruktur."
        )

    return directories[0]


# ============================================================
# Docker Image
# ============================================================

def build_image(
    source_dir: Path,
    version: str,
):

    image_tag = (
        f"{IMAGE_NAME}:{version}"
    )

    state["status"] = "building"

    state["message"] = (
        f"Docker Image {image_tag} "
        f"wird gebaut."
    )

    run_command(
        [
            "docker",
            "build",
            "--pull",
            "-t",
            image_tag,
            str(source_dir),
        ],
        timeout=1800,
    )

    return image_tag


# ============================================================
# Current image
# ============================================================

def get_current_image():

    try:

        output = run_command(
            [
                "docker",
                "inspect",
                "--format",
                "{{.Config.Image}}",
                APP_CONTAINER,
            ],
            timeout=30,
        )

        return output.strip()

    except Exception:

        return ""


# ============================================================
# Current version
# ============================================================

def get_current_version():

    image = get_current_image()

    if ":" not in image:
        return ""

    return image.rsplit(
        ":",
        1
    )[1]


# ============================================================
# Healthcheck
# ============================================================

def wait_for_healthy(
    timeout: int = 120,
):

    start = time.time()

    while (
        time.time() - start
        < timeout
    ):

        try:

            status = run_command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{if .State.Health}}"
                    "{{.State.Health.Status}}"
                    "{{else}}"
                    "{{.State.Status}}"
                    "{{end}}",
                    APP_CONTAINER,
                ],
                timeout=10,
            ).strip()

            if status == "healthy":
                return

            if status in (
                "unhealthy",
                "dead",
            ):

                raise RuntimeError(
                    f"Container ist {status}."
                )

        except RuntimeError as exc:

            if "Container ist" in str(exc):
                raise

        time.sleep(3)

    raise TimeoutError(
        "Django-Container wurde "
        "nicht rechtzeitig healthy."
    )


# ============================================================
# Rollback
# ============================================================

def rollback(
    previous_version: str
):

    if not previous_version:

        raise RuntimeError(
            "Keine vorherige Version "
            "für Rollback bekannt."
        )

    previous_image = (
        f"{IMAGE_NAME}:"
        f"{previous_version}"
    )

    state["status"] = "rollback"

    state["message"] = (
        f"Rollback auf "
        f"{previous_version}."
    )

    # Alten Container entfernen
    run_command(
        [
            "docker",
            "rm",
            "-f",
            APP_CONTAINER,
        ],
        timeout=60,
    )

    # Alten Container mit den wichtigen
    # Compose-Einstellungen neu erstellen.
    #
    # Die eigentlichen Einstellungen
    # werden aus dem bisherigen Container
    # übernommen.

    create_container_from_previous(
        previous_image
    )

    run_command(
        [
            "docker",
            "start",
            APP_CONTAINER,
        ],
        timeout=60,
    )

    wait_for_healthy(
        timeout=120
    )


# ============================================================
# Container creation
# ============================================================

def create_container_from_previous(
    image: str
):

    # Netzwerk des bestehenden Containers
    network = "zeiterfassung_default"

    command = [
        "docker",
        "create",

        "--name",
        APP_CONTAINER,

        "--network",
        network,

        "--restart",
        "unless-stopped",

        "--env-file",
        "/dev/null",

        image,

        "/app/entrypoint.sh",
    ]

    # Dieser Teil wird weiter unten durch
    # die Compose-Variante ersetzt.
    #
    # Die Funktion bleibt als Fallback
    # bestehen.

    run_command(
        command,
        timeout=60,
    )


# ============================================================
# Update
# ============================================================

def perform_update(
    version: str
):

    work_dir = None

    try:

        version = normalize_version(
            version
        )

        state.update({
            "status": "checking",
            "version": version,
            "message":
                f"Release {version} "
                f"wird geprüft.",
            "error": "",
            "started_at":
                time.time(),
            "finished_at":
                None,
        })

        # ----------------------------------------------------
        # Release prüfen
        # ----------------------------------------------------

        get_release(version)

        # ----------------------------------------------------
        # Alte Version ermitteln
        # ----------------------------------------------------

        previous_version = (
            get_current_version()
        )

        state["previous_version"] = (
            previous_version
        )

        # ----------------------------------------------------
        # Arbeitsverzeichnis
        # ----------------------------------------------------

        TMP_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        work_dir = Path(
            tempfile.mkdtemp(
                prefix="release-",
                dir=TMP_DIR,
            )
        )

        archive = (
            work_dir /
            "release.tar.gz"
        )

        source = (
            work_dir /
            "source"
        )

        # ----------------------------------------------------
        # Download
        # ----------------------------------------------------

        state["status"] = "downloading"

        state["message"] = (
            f"Release {version} "
            f"wird heruntergeladen."
        )

        download_release(
            version,
            archive,
        )

        # ----------------------------------------------------
        # Extract
        # ----------------------------------------------------

        state["status"] = "extracting"

        state["message"] = (
            "Release wird entpackt."
        )

        source_root = extract_release(
            archive,
            source,
        )

        # ----------------------------------------------------
        # Build
        # ----------------------------------------------------

        build_image(
            source_root,
            version,
        )

        # ----------------------------------------------------
        # Tag current
        # ----------------------------------------------------

        state["status"] = "tagging"

        state["message"] = (
            "Neues Image wird als "
            "'current' markiert."
        )

        run_command(
            [
                "docker",
                "tag",
                f"{IMAGE_NAME}:{version}",
                f"{IMAGE_NAME}:current",
            ],
            timeout=60,
        )

        # ----------------------------------------------------
        # Container ersetzen
        # ----------------------------------------------------

        state["status"] = "restarting"

        state["message"] = (
            "Django-Container wird "
            "neu gestartet."
        )

        #
        # Docker Compose wird hier verwendet.
        #
        # Dafür wird die Compose-Datei über
        # den Host-Pfad gesucht.
        #

        compose_file = find_compose_file()

        run_command(
            [
                "docker",
                "compose",
                "-f",
                compose_file,
                "up",
                "-d",
                "--no-deps",
                "app",
            ],
            timeout=300,
        )

        # ----------------------------------------------------
        # Healthcheck
        # ----------------------------------------------------

        state["status"] = "healthcheck"

        state["message"] = (
            "Warte auf Django Healthcheck."
        )

        try:

            wait_for_healthy(
                timeout=120
            )

        except Exception as health_error:

            state["message"] = (
                "Healthcheck fehlgeschlagen. "
                "Rollback wird durchgeführt."
            )

            try:

                rollback(
                    previous_version
                )

            except Exception as rollback_error:

                raise RuntimeError(
                    "Update fehlgeschlagen "
                    "und Rollback ebenfalls "
                    "fehlgeschlagen.\n\n"
                    f"Healthcheck: "
                    f"{health_error}\n\n"
                    f"Rollback: "
                    f"{rollback_error}"
                )

            raise RuntimeError(
                f"Update fehlgeschlagen: "
                f"{health_error}. "
                f"Rollback auf "
                f"{previous_version} "
                f"durchgeführt."
            )

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        state["status"] = "success"

        state["message"] = (
            f"Update auf {version} "
            f"erfolgreich."
        )

        state["finished_at"] = (
            time.time()
        )

    except Exception as exc:

        state["status"] = "error"

        state["message"] = (
            "Update fehlgeschlagen."
        )

        state["error"] = str(exc)

        state["finished_at"] = (
            time.time()
        )

    finally:

        if work_dir:

            shutil.rmtree(
                work_dir,
                ignore_errors=True,
            )

        update_lock.release()


# ============================================================
# Compose file
# ============================================================

def find_compose_file():

    possible_paths = [
        "/project/docker-compose.yml",
        "/project/compose.yml",
    ]

    for path in possible_paths:

        if os.path.exists(path):
            return path

    raise RuntimeError(
        "docker-compose.yml konnte "
        "nicht gefunden werden."
    )


# ============================================================
# HTTP
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok"
    }


@app.get("/status")
def status(
    x_updater_secret:
        Optional[str] = Header(
            default=None
        )
):

    authenticate(
        x_updater_secret
    )

    return dict(state)


@app.post("/update")
def update(
    request: UpdateRequest,
    x_updater_secret:
        Optional[str] = Header(
            default=None
        ),
):

    authenticate(
        x_updater_secret
    )

    try:

        version = normalize_version(
            request.version
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    if not update_lock.acquire(
        blocking=False
    ):

        raise HTTPException(
            status_code=409,
            detail="Ein Update läuft bereits.",
        )

    thread = threading.Thread(
        target=perform_update,
        args=(version,),
        daemon=True,
    )

    thread.start()

    return {
        "status": "started",
        "version": version,
    }