import io
import os
import tempfile
import zipfile
import shutil

import docker
import requests

from fastapi import FastAPI, Header, HTTPException, Body

from datetime import datetime

import time

import subprocess
import threading

app = FastAPI()


UPDATER_SECRET = os.environ["UPDATER_SECRET"]

GITHUB_REPO = "Niklwas/Zeiterfassung"

REQUIRED_FILES = [
    "manage.py",
    "Dockerfile",
    "docker-compose.yml",
]

REQUIRED_DIRECTORIES = [
    "core",
    "setting",
    "zeiterfassung",
]

PROJECT_PATH = "/project"
UPDATE_PATH = "/project/.update"
BACKUP_PATH = "/project/.backup"

BACKUP_EXCLUDE = {
    ".update",
    ".backup",
}

UPDATE_EXCLUDE = {
    ".env",
    ".env.prod",
    ".env.local",
    ".backup",
    ".update",
    ".git",
}

APP_HEALTH_URL = os.environ.get(
    "APP_HEALTH_URL",
    "http://app:8000/health/",
)

install_status = {
    "status": "idle",
    "phase": "",
    "version": "",
    "current_version": "",
    "error": "",
    "log": "",
    "started_at": "",
    "finished_at": "",
    "rollback": False,
    "backup": "",
    "rollback_image": "",
    "current_image": "",
}

COMPOSE_PROJECT = "zeiterfassung"
COMPOSE_FILE = "/project/docker-compose.yml"


def check_secret(token: str | None):
    if token != UPDATER_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )


@app.get("/status")
def status(
    x_updater_secret: str | None = Header(default=None),
):
    check_secret(x_updater_secret)

    return install_status.copy()


@app.get("/docker")
def docker_status(
    x_updater_secret: str | None = Header(default=None),
):
    check_secret(x_updater_secret)

    try:
        client = docker.from_env()

        info = client.info()

        return {
            "status": "ok",
            "docker_version": client.version()["Version"],
            "containers": info["Containers"],
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.get("/project")
def project_status(
    x_updater_secret: str | None = Header(default=None),
):
    check_secret(x_updater_secret)

    project_path = "/project"

    try:
        entries = sorted(os.listdir(project_path))

        return {
            "status": "ok",
            "project_path": project_path,
            "entries": entries,
            "compose_file": os.path.exists(
                os.path.join(
                    project_path,
                    "docker-compose.yml",
                )
            ),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@app.post("/update")
def update(
    x_updater_secret: str | None = Header(default=None),
    version: str = "latest",
    payload: dict = Body(default={}),
):
    check_secret(x_updater_secret)

    # ------------------------------------------------------------
    # Version aus Request bestimmen
    # ------------------------------------------------------------

    requested_version = payload.get("version") or version

    if not requested_version or requested_version == "latest":
        raise HTTPException(
            status_code=400,
            detail="Keine konkrete Version angegeben.",
        )

    requested_version = str(
        requested_version
    ).strip()

    # ------------------------------------------------------------
    # Verhindern, dass zwei Updates gleichzeitig laufen
    # ------------------------------------------------------------

    if install_status["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail="Ein Update läuft bereits.",
        )

    # ------------------------------------------------------------
    # Status initialisieren
    # ------------------------------------------------------------

    install_status.update({
        "status": "running",
        "phase": "prepare",
        "version": requested_version,
        "current_version": "",
        "error": "",
        "log": "",
        "started_at": datetime.now().isoformat(),
        "finished_at": "",
        "rollback": False,
        "backup": "",
        "rollback_image": "",
        "current_image": "",
    })

    log(
        "Update wurde gestartet.",
        "prepare",
    )

    # ------------------------------------------------------------
    # Update im Hintergrund starten
    # ------------------------------------------------------------

    thread = threading.Thread(
        target=run_update,
        args=(requested_version,),
        daemon=True,
    )

    thread.start()

    # ------------------------------------------------------------
    # Sofort antworten
    # ------------------------------------------------------------

    return {
        "status": "accepted",
        "message": "Update wurde im Hintergrund gestartet.",
        "version": requested_version,
    }


def run_update(version: str) -> None:

    try:
        # --------------------------------------------------------
        # 1. Release vorbereiten
        # --------------------------------------------------------

        log(
            f"Bereite Release {version} vor.",
            "prepare",
        )

        prepared = prepare_release(version)

        install_status["version"] = prepared["version"]

        log(
            f"Release {prepared['version']} wurde vorbereitet.",
            "prepare",
        )

        # --------------------------------------------------------
        # 2. Projekt-Backup
        # --------------------------------------------------------

        log(
            "Erstelle Projekt-Backup.",
            "backup",
        )

        backup = create_backup()

        install_status["backup"] = backup["path"]

        log(
            f"Projekt-Backup erstellt: {backup['path']}",
            "backup",
        )

        # --------------------------------------------------------
        # 3. Aktuelles Docker-Image sichern
        # --------------------------------------------------------

        log(
            "Sichere aktuelles Docker-Image.",
            "backup",
        )

        current_image = "zeiterfassung-app:latest"

        install_status["current_image"] = current_image

        rollback_image = backup_current_image()

        install_status["rollback_image"] = rollback_image

        log(
            f"Docker-Image gesichert: {rollback_image}",
            "backup",
        )

        # --------------------------------------------------------
        # 4. Release-Dateien installieren
        # --------------------------------------------------------

        log(
            "Installiere Release-Dateien.",
            "install",
        )

        sync_release_files(
            prepared["path"]
        )

        remove_empty_and_obsolete_directories()

        log(
            "Release-Dateien wurden installiert.",
            "install",
        )

        # --------------------------------------------------------
        # 5. Docker-Image bauen
        # --------------------------------------------------------

        log(
            "Baue neues Docker-Image.",
            "build",
        )

        compose(
            "build",
            "app",
        )

        log(
            "Neues Docker-Image wurde erfolgreich gebaut.",
            "build",
        )

        # --------------------------------------------------------
        # 6. App neu starten
        # --------------------------------------------------------

        log(
            "Starte App mit dem neuen Docker-Image.",
            "restart",
        )

        compose(
            "up",
            "-d",
            "--no-deps",
            "app",
        )

        log(
            "App-Container wurde neu gestartet.",
            "restart",
        )

        # --------------------------------------------------------
        # 7. Healthcheck
        # --------------------------------------------------------

        log(
            "Warte auf die gestartete App.",
            "health",
        )

        healthy = check_app_health(
            timeout=60,
            interval=2,
        )

        if not healthy:
            raise RuntimeError(
                "App-Healthcheck fehlgeschlagen."
            )

        log(
            "App-Healthcheck erfolgreich.",
            "health",
        )

        # --------------------------------------------------------
        # 8. Installierte Version prüfen
        # --------------------------------------------------------

        log(
            "Prüfe die installierte App-Version.",
            "verify",
        )

        current_version = get_app_version()

        install_status["current_version"] = current_version

        if current_version != version.lstrip("v"):
            raise RuntimeError(
                "Versionsprüfung fehlgeschlagen: "
                f"erwartet {version.lstrip('v')}, "
                f"gefunden {current_version}"
            )

        log(
            f"Versionsprüfung erfolgreich: {current_version}",
            "verify",
        )

        # --------------------------------------------------------
        # 9. Update erfolgreich
        # --------------------------------------------------------

        install_status["status"] = "success"
        install_status["phase"] = "completed"
        install_status["rollback"] = False
        install_status["finished_at"] = datetime.now().isoformat()

        log(
            "Update erfolgreich abgeschlossen.",
            "completed",
        )

        cleanup_update_directory()

    except Exception as exc:

        # --------------------------------------------------------
        # Update fehlgeschlagen
        # --------------------------------------------------------

        install_status["error"] = str(exc)

        log(
            f"Update fehlgeschlagen: {exc}",
            "error",
        )

        # --------------------------------------------------------
        # Rollback versuchen
        # --------------------------------------------------------

        rollback_image = install_status.get(
            "rollback_image"
        )

        if rollback_image:

            try:
                install_status["rollback"] = True

                log(
                    "Starte die App mit dem vorherigen Stand.",
                    "rollback",
                )

                restore_image(
                    rollback_image
                )

                compose(
                    "up",
                    "-d",
                    "--no-deps",
                    "app",
                )

                log(
                    "Prüfe die wiederhergestellte App.",
                    "rollback",
                )

                healthy = check_app_health(
                    timeout=60,
                    interval=2,
                )

                if healthy:
                    log(
                        "Rollback erfolgreich abgeschlossen.",
                        "rollback",
                    )
                else:
                    log(
                        "Rollback wurde durchgeführt, "
                        "aber der Healthcheck ist fehlgeschlagen.",
                        "rollback",
                    )

            except Exception as rollback_exc:

                install_status["error"] += (
                    f" | Rollback fehlgeschlagen: "
                    f"{rollback_exc}"
                )

                log(
                    f"Rollback fehlgeschlagen: {rollback_exc}",
                    "rollback",
                )

        # --------------------------------------------------------
        # Endstatus
        # --------------------------------------------------------

        install_status["status"] = "error"
        install_status["phase"] = "error"
        install_status["finished_at"] = datetime.now().isoformat()

        cleanup_update_directory()


def safe_extract_zip(
    zip_data: bytes,
    destination: str,
):
    os.makedirs(
        destination,
        exist_ok=True,
    )

    destination = os.path.abspath(destination)

    with zipfile.ZipFile(
        io.BytesIO(zip_data)
    ) as archive:

        for member in archive.infolist():

            member_path = os.path.abspath(
                os.path.join(
                    destination,
                    member.filename,
                )
            )

            if not (
                member_path == destination
                or member_path.startswith(
                    destination + os.sep
                )
            ):
                raise ValueError(
                    f"Unsicherer ZIP-Pfad erkannt: {member.filename}"
                )

        archive.extractall(destination)


def download_release(version: str) -> bytes:
    version = version.strip()

    if not version:
        raise ValueError(
            "Keine Version angegeben."
        )

    if not version.startswith("v"):
        version = f"v{version}"

    url = (
        f"https://github.com/{GITHUB_REPO}"
        f"/archive/refs/tags/{version}.zip"
    )

    response = requests.get(
        url,
        timeout=60,
    )

    response.raise_for_status()

    if not response.content:
        raise ValueError(
            "GitHub hat ein leeres Release geliefert."
        )

    return response.content


def prepare_release(version: str) -> dict:
    if not version.startswith("v"):
        version = f"v{version}"

    update_root = "/project/.update"

    release_dir = os.path.join(
        update_root,
        version,
    )

    if os.path.exists(release_dir):
        import shutil

        shutil.rmtree(release_dir)

    os.makedirs(
        update_root,
        exist_ok=True,
    )

    zip_data = download_release(version)

    with tempfile.TemporaryDirectory(
        prefix="zeiterfassung-download-"
    ) as temp_dir:

        extract_dir = os.path.join(
            temp_dir,
            "release",
        )

        safe_extract_zip(
            zip_data,
            extract_dir,
        )

        entries = sorted(
            os.listdir(extract_dir)
        )

        if len(entries) != 1:
            raise ValueError(
                "Unerwartete ZIP-Struktur."
            )

        release_root = os.path.join(
            extract_dir,
            entries[0],
        )

        if not os.path.isdir(release_root):
            raise ValueError(
                "Release enthält keinen Hauptordner."
            )

        validate_release_structure(
            release_root
        )

        import shutil

        shutil.copytree(
            release_root,
            release_dir,
        )

    return {
        "version": version,
        "path": release_dir,
    }


def validate_release_structure(
    release_root: str,
):
    missing_files = []

    for filename in REQUIRED_FILES:
        path = os.path.join(
            release_root,
            filename,
        )

        if not os.path.isfile(path):
            missing_files.append(filename)

    missing_directories = []

    for dirname in REQUIRED_DIRECTORIES:
        path = os.path.join(
            release_root,
            dirname,
        )

        if not os.path.isdir(path):
            missing_directories.append(dirname)

    if missing_files or missing_directories:
        raise ValueError(
            {
                "message": "Release-Struktur ist ungültig.",
                "missing_files": missing_files,
                "missing_directories": missing_directories,
            }
        )


def cleanup_update_directory():
    update_root = "/project/.update"

    if os.path.exists(update_root):
        import shutil

        shutil.rmtree(update_root)


def create_backup() -> dict:
    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    backup_dir = os.path.join(
        BACKUP_PATH,
        timestamp,
    )

    os.makedirs(
        BACKUP_PATH,
        exist_ok=True,
    )

    os.makedirs(
        backup_dir,
        exist_ok=True,
    )

    for entry in os.listdir(PROJECT_PATH):

        if entry in BACKUP_EXCLUDE:
            continue

        source = os.path.join(
            PROJECT_PATH,
            entry,
        )

        destination = os.path.join(
            backup_dir,
            entry,
        )

        if os.path.isdir(source):
            shutil.copytree(
                source,
                destination,
            )

        else:
            shutil.copy2(
                source,
                destination,
            )

    cleanup_old_backups(max_backups=3)

    return {
        "backup": timestamp,
        "path": backup_dir,
    }


def cleanup_old_backups(max_backups: int = 3) -> None:
    if not os.path.isdir(BACKUP_PATH):
        return

    backups = []

    for entry in os.listdir(BACKUP_PATH):
        path = os.path.join(
            BACKUP_PATH,
            entry,
        )

        if not os.path.isdir(path):
            continue

        backups.append(entry)

    backups.sort(reverse=True)

    old_backups = backups[max_backups:]

    for backup in old_backups:
        path = os.path.join(
            BACKUP_PATH,
            backup,
        )

        shutil.rmtree(path)

        log(
            f"Altes Projekt-Backup gelöscht: {path}",
            "backup",
        )


def install_release_files(release_dir: str):
    if not os.path.isdir(release_dir):
        raise ValueError(
            f"Release-Verzeichnis existiert nicht: {release_dir}"
        )

    for entry in os.listdir(release_dir):

        if entry in UPDATE_EXCLUDE:
            continue

        source = os.path.join(
            release_dir,
            entry,
        )

        destination = os.path.join(
            PROJECT_PATH,
            entry,
        )

        if os.path.isdir(source):

            if os.path.exists(destination):
                shutil.rmtree(destination)

            shutil.copytree(
                source,
                destination,
            )

        else:

            os.makedirs(
                os.path.dirname(destination),
                exist_ok=True,
            )

            shutil.copy2(
                source,
                destination,
            )


def get_release_changes(release_dir: str) -> dict:
    files = []
    directories = []

    for root, dirnames, filenames in os.walk(
        release_dir
    ):
        relative_root = os.path.relpath(
            root,
            release_dir,
        )

        if relative_root == ".":
            relative_root = ""

        dirnames[:] = [
            name
            for name in dirnames
            if name not in UPDATE_EXCLUDE
        ]

        for dirname in dirnames:
            relative_path = os.path.join(
                relative_root,
                dirname,
            )

            directories.append(
                relative_path
            )

        for filename in filenames:
            if filename in UPDATE_EXCLUDE:
                continue

            relative_path = os.path.join(
                relative_root,
                filename,
            )

            files.append(
                relative_path
            )

    return {
        "files": sorted(files),
        "directories": sorted(directories),
    }


def get_relative_files(root: str) -> set[str]:
    result = set()

    for current_root, _, filenames in os.walk(root):
        for filename in filenames:
            absolute_path = os.path.join(
                current_root,
                filename,
            )

            relative_path = os.path.relpath(
                absolute_path,
                root,
            )

            result.add(relative_path)

    return result


def sync_release_files(release_dir: str):
    """
    Synchronisiert das vorbereitete Release mit dem Projekt.

    Geschützt:
    - .env
    - .env.prod
    - .env.local
    - .backup
    - .update
    - .git
    """

    release_dir = os.path.abspath(release_dir)
    project_dir = os.path.abspath(PROJECT_PATH)

    if not os.path.isdir(release_dir):
        raise ValueError(
            f"Release-Verzeichnis existiert nicht: {release_dir}"
        )

    # ------------------------------------------------------------
    # 1. Dateien aus dem alten Projekt entfernen,
    #    die im neuen Release nicht mehr vorhanden sind.
    # ------------------------------------------------------------

    release_files = get_relative_files(
        release_dir
    )

    project_files = get_relative_files(
        project_dir
    )

    for relative_path in project_files:

        first_component = relative_path.split(
            os.sep,
            1,
        )[0]

        if first_component in UPDATE_EXCLUDE:
            continue

        if relative_path in release_files:
            continue

        project_file = os.path.join(
            project_dir,
            relative_path,
        )

        if os.path.isfile(project_file):
            os.remove(project_file)

    # ------------------------------------------------------------
    # 2. Release-Dateien kopieren.
    # ------------------------------------------------------------

    for current_root, dirnames, filenames in os.walk(
        release_dir
    ):

        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in UPDATE_EXCLUDE
        ]

        relative_root = os.path.relpath(
            current_root,
            release_dir,
        )

        if relative_root == ".":
            relative_root = ""

        for filename in filenames:

            if filename in UPDATE_EXCLUDE:
                continue

            relative_path = os.path.join(
                relative_root,
                filename,
            )

            source = os.path.join(
                release_dir,
                relative_path,
            )

            destination = os.path.join(
                project_dir,
                relative_path,
            )

            os.makedirs(
                os.path.dirname(destination),
                exist_ok=True,
            )

            shutil.copy2(
                source,
                destination,
            )


def remove_empty_and_obsolete_directories():
    """
    Entfernt leere bzw. nicht mehr benötigte Verzeichnisse
    aus dem Projekt.

    Geschützte Verzeichnisse werden niemals angefasst.
    """

    protected = UPDATE_EXCLUDE

    for current_root, dirnames, _ in os.walk(
        PROJECT_PATH,
        topdown=False,
    ):

        for dirname in dirnames:

            if dirname in protected:
                continue

            directory = os.path.join(
                current_root,
                dirname,
            )

            if not os.path.isdir(directory):
                continue

            try:
                os.rmdir(directory)
            except OSError:
                pass


def safe_project_path(relative_path: str) -> str:
    project_dir = os.path.abspath(
        PROJECT_PATH
    )

    target = os.path.abspath(
        os.path.join(
            project_dir,
            relative_path,
        )
    )

    if not (
        target == project_dir
        or target.startswith(
            project_dir + os.sep
        )
    ):
        raise ValueError(
            f"Unsicherer Projektpfad: {relative_path}"
        )

    return target


def perform_file_update(version: str) -> dict:
    # 1. Release herunterladen und vorbereiten
    prepared = prepare_release(version)

    # 2. Backup erstellen
    backup = create_backup()

    # 3. Dateien synchronisieren
    sync_release_files(
        prepared["path"]
    )

    # 4. Leere Verzeichnisse entfernen
    remove_empty_and_obsolete_directories()

    return {
        "version": prepared["version"],
        "release_path": prepared["path"],
        "backup": backup,
    }


def check_app_health(
    timeout: int = 60,
    interval: int = 2,
) -> dict:
    """
    Wartet darauf, dass die Django-Anwendung wieder erreichbar ist.
    """

    start = time.monotonic()
    last_error = ""

    while time.monotonic() - start < timeout:

        try:
            response = requests.get(
                APP_HEALTH_URL,
                timeout=5,
            )

            if response.status_code == 200:

                try:
                    data = response.json()
                except ValueError:
                    data = {}

                if data.get("status") == "ok":
                    return {
                        "status": "ok",
                        "http_status": response.status_code,
                        "url": APP_HEALTH_URL,
                    }

                last_error = (
                    f"Ungültige Healthcheck-Antwort: "
                    f"{response.text[:500]}"
                )

            else:
                last_error = (
                    f"HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                )

        except requests.RequestException as exc:
            last_error = str(exc)

        time.sleep(interval)

    raise RuntimeError(
        f"Healthcheck fehlgeschlagen: {last_error}"
    )


def get_current_app_image() -> str:
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.Config.Image}}",
            "django-app",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    image = result.stdout.strip()

    if not image:
        raise RuntimeError(
            "Aktuelles App-Image konnte nicht ermittelt werden."
        )

    return image


def backup_current_app_image(
    timestamp: str,
) -> str:

    current_image = get_current_app_image()

    rollback_image = (
        f"zeiterfassung-app:"
        f"rollback-{timestamp}"
    )

    subprocess.run(
        [
            "docker",
            "tag",
            current_image,
            rollback_image,
        ],
        check=True,
    )

    return rollback_image


def restore_backup(
    backup_dir: str,
):
    if not os.path.isdir(backup_dir):
        raise ValueError(
            f"Backup existiert nicht: {backup_dir}"
        )

    for entry in os.listdir(PROJECT_PATH):

        if entry in UPDATE_EXCLUDE:
            continue

        target = os.path.join(
            PROJECT_PATH,
            entry,
        )

        if os.path.isdir(target):
            shutil.rmtree(target)

        elif os.path.isfile(target):
            os.remove(target)

    for entry in os.listdir(backup_dir):

        source = os.path.join(
            backup_dir,
            entry,
        )

        target = os.path.join(
            PROJECT_PATH,
            entry,
        )

        if os.path.isdir(source):
            shutil.copytree(
                source,
                target,
            )

        else:
            shutil.copy2(
                source,
                target,
            )


def restore_app_image(
    rollback_image: str,
):
    subprocess.run(
        [
            "docker",
            "tag",
            rollback_image,
            "zeiterfassung-app:latest",
        ],
        check=True,
    )

    subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "zeiterfassung",
            "-f",
            "/project/docker-compose.yml",
            "up",
            "-d",
            "--no-deps",
            "app",
        ],
        check=True,
    )


def rollback_app(
    rollback_image: str,
) -> dict:

    try:
        subprocess.run(
            [
                "docker",
                "tag",
                rollback_image,
                "zeiterfassung-app:latest",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                "zeiterfassung",
                "-f",
                "/project/docker-compose.yml",
                "up",
                "-d",
                "--no-deps",
                "app",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        health = check_app_health(
            timeout=60,
            interval=2,
        )

        return {
            "status": "ok",
            "health": health,
        }

    except subprocess.CalledProcessError as exc:

        raise RuntimeError(
            "Rollback konnte nicht durchgeführt werden: "
            + (exc.stderr or str(exc))
        )


def log(
    message: str,
    phase: str | None = None,
) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")

    if phase is not None:
        install_status["phase"] = phase

    install_status["log"] += (
        f"[{timestamp}] {message}\n"
    )

    print(f"[{timestamp}] {message}", flush=True)


def compose(*args: str) -> subprocess.CompletedProcess:
    command = [
        "docker",
        "compose",
        "-p",
        COMPOSE_PROJECT,
        "-f",
        COMPOSE_FILE,
        *args,
    ]

    log("Docker: " + " ".join(command))

    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def backup_current_image() -> str:
    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    backup_tag = (
        f"zeiterfassung-app:"
        f"rollback-{timestamp}"
    )

    log(
        f"Sichere aktuelles Image als {backup_tag}"
    )

    subprocess.run(
        [
            "docker",
            "tag",
            "zeiterfassung-app:latest",
            backup_tag,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    cleanup_old_rollback_images(max_images=3)

    return backup_tag


def cleanup_old_rollback_images(max_images: int = 3) -> None:
    result = subprocess.run(
        [
            "docker",
            "image",
            "ls",
            "zeiterfassung-app",
            "--format",
            "{{.Tag}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    tags = []

    for line in result.stdout.splitlines():
        tag = line.strip()

        if tag.startswith("rollback-"):
            tags.append(tag)

    tags.sort(reverse=True)

    old_tags = tags[max_images:]

    for tag in old_tags:
        image = f"zeiterfassung-app:{tag}"

        log(
            f"Altes Rollback-Image wird gelöscht: {image}",
            "backup",
        )

        subprocess.run(
            [
                "docker",
                "image",
                "rm",
                image,
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def restore_image(rollback_tag: str) -> None:
    log(
        f"Stelle Docker Image wieder her: "
        f"{rollback_tag}"
    )

    subprocess.run(
        [
            "docker",
            "tag",
            rollback_tag,
            "zeiterfassung-app:latest",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def check_app_health(
    timeout: int = 60,
    interval: int = 2,
) -> bool:

    log("Starte App-Healthcheck")

    deadline = time.time() + timeout

    while time.time() < deadline:

        try:
            result = subprocess.run(
                [
                    "python",
                    "-c",
                    (
                        "import requests; "
                        "r=requests.get("
                        "'http://app:8000/health/', "
                        "timeout=5"
                        "); "
                        "print(r.status_code); "
                        "raise SystemExit("
                        "0 if r.status_code == 200 "
                        "else 1"
                        ")"
                    ),
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                log("Healthcheck erfolgreich")
                return True

        except Exception:
            pass

        time.sleep(interval)

    log("Healthcheck fehlgeschlagen")

    return False


def get_app_version() -> str:
    log("Ermittle aktuelle App-Version")

    result = subprocess.run(
        [
            "docker",
            "exec",
            "django-app",
            "python",
            "-c",
            (
                "import sys; "
                "sys.path.insert(0, '/app'); "
                "from version import VERSION; "
                "print(VERSION)"
            ),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "App-Version konnte nicht ermittelt werden: "
            + result.stderr.strip()
        )

    version = result.stdout.strip()

    if not version:
        raise RuntimeError(
            "App-Version ist leer."
        )

    log(f"Aktuelle App-Version: {version}")

    return version

