import json
import os
import shutil
import ssl
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

import docker
from docker.errors import DockerException, NotFound


# ==========================================================
# KONFIGURATION
# ==========================================================

REPO_URL = "https://github.com/Niklwas/Zeiterfassung.git"

PROJECT_DIR = Path(
    os.environ.get(
        "PROJECT_DIR",
        "/app",
    )
)

BACKUP_DIR = PROJECT_DIR / "sich"
TMP_DIR = PROJECT_DIR / ".update_tmp"

STATUS_FILE = Path(
    os.environ.get(
        "UPDATER_STATUS_FILE",
        "/var/log/django/update-status.json",
    )
)

LOG_FILE = Path(
    os.environ.get(
        "UPDATER_LOG_FILE",
        "/var/log/django/update.log",
    )
)

POSTGRES_CONTAINER = os.environ.get(
    "POSTGRES_CONTAINER",
    "django-postgres",
)

APP_CONTAINER = os.environ.get(
    "APP_CONTAINER",
    "django-app",
)

APP_IMAGE = os.environ.get(
    "APP_IMAGE",
    "zeiterfassung-app",
)

APP_PORT = int(
    os.environ.get(
        "APP_PORT",
        "8000",
    )
)

# Der Updater versucht diesen internen
# Django-Endpunkt zu erreichen.
#
# Falls du später einen echten /health/ Endpoint
# hast, kannst du hier /health/ verwenden.
APP_HEALTH_PATH = os.environ.get(
    "APP_HEALTH_PATH",
    "/admin/login/",
)


# ==========================================================
# DOCKER CLIENT
# ==========================================================

def get_docker_client():

    try:

        client = docker.from_env()

        client.ping()

        return client

    except DockerException as exc:

        raise RuntimeError(
            f"Docker API nicht erreichbar: {exc}"
        ) from exc


docker_client = get_docker_client()


# ==========================================================
# VERZEICHNISSE
# ==========================================================

LOG_FILE.parent.mkdir(
    parents=True,
    exist_ok=True,
)

STATUS_FILE.parent.mkdir(
    parents=True,
    exist_ok=True,
)


# ==========================================================
# LOGGING
# ==========================================================

def timestamp():

    return time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def log(message):

    line = (
        f"[{timestamp()}] {message}"
    )

    print(
        line,
        flush=True,
    )

    try:

        with LOG_FILE.open(
            "a",
            encoding="utf-8",
        ) as f:

            f.write(
                line + "\n"
            )

    except Exception:
        pass


# ==========================================================
# STATUS
# ==========================================================

_status_lock = threading.Lock()


def write_status(
    status,
    version="",
    error="",
):

    data = {
        "status": status,
        "version": version,
        "error": error,
        "log": "",
    }

    try:

        if LOG_FILE.exists():

            data["log"] = (
                LOG_FILE.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[-30000:]
            )

    except Exception:
        pass

    STATUS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = STATUS_FILE.with_suffix(
        ".tmp"
    )

    with _status_lock:

        with temporary.open(
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        temporary.replace(
            STATUS_FILE
        )


def read_status():

    if not STATUS_FILE.exists():

        return {
            "status": "idle",
            "version": "",
            "error": "",
            "log": "",
        }

    try:

        with STATUS_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(f)

    except Exception as exc:

        return {
            "status": "failed",
            "version": "",
            "error": str(exc),
            "log": "",
        }


# ==========================================================
# EXTERNE BEFEHLE
#
# Nur für Git.
#
# Docker wird NICHT über die Docker CLI verwendet.
# ==========================================================

def run_command(
    command,
    cwd=None,
):

    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Befehl fehlgeschlagen:\n"
            f"{' '.join(command)}\n"
            f"{result.stderr}"
        )

    return result.stdout


# ==========================================================
# CONTAINER
# ==========================================================

def get_container(
    container_name,
):

    try:

        return docker_client.containers.get(
            container_name
        )

    except NotFound as exc:

        raise RuntimeError(
            f"Container '{container_name}' "
            "nicht gefunden."
        ) from exc


def container_running(
    container_name,
):

    try:

        container = (
            docker_client.containers.get(
                container_name
            )
        )

        container.reload()

        return (
            container.status == "running"
        )

    except NotFound:

        return False


def wait_for_container(
    container_name,
    timeout=60,
):

    log(
        f"Warte auf {container_name}..."
    )

    start = time.time()

    while (
        time.time() - start
        < timeout
    ):

        try:

            container = get_container(
                container_name
            )

            container.reload()

            if (
                container.status
                == "running"
            ):

                log(
                    f"{container_name} läuft."
                )

                return True

        except Exception:
            pass

        time.sleep(2)

    return False


# ==========================================================
# POSTGRESQL BACKUP
# ==========================================================

def backup_postgres():

    log(
        "Erstelle PostgreSQL-Backup..."
    )

    container = get_container(
        POSTGRES_CONTAINER
    )

    container.reload()

    if container.status != "running":

        raise RuntimeError(
            "PostgreSQL-Container läuft nicht."
        )

    postgres_user = os.environ.get(
        "POSTGRES_USER"
    )

    postgres_db = os.environ.get(
        "POSTGRES_DB"
    )

    postgres_password = os.environ.get(
        "POSTGRES_PASSWORD"
    )

    if not postgres_user:

        raise RuntimeError(
            "POSTGRES_USER fehlt."
        )

    if not postgres_db:

        raise RuntimeError(
            "POSTGRES_DB fehlt."
        )

    if not postgres_password:

        raise RuntimeError(
            "POSTGRES_PASSWORD fehlt."
        )

    result = container.exec_run(
        [
            "pg_dump",
            "-U",
            postgres_user,
            "-d",
            postgres_db,
        ],
        environment={
            "PGPASSWORD": postgres_password,
        },
    )

    if result.exit_code != 0:

        output = (
            result.output.decode(
                "utf-8",
                errors="replace",
            )
        )

        raise RuntimeError(
            "PostgreSQL-Backup "
            f"fehlgeschlagen:\n{output}"
        )

    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    backup_file = (
        BACKUP_DIR /
        "django_backup.sql"
    )

    backup_file.write_bytes(
        result.output
    )

    log(
        "PostgreSQL-Backup erstellt."
    )

    log(
        f"Backup-Datei: {backup_file}"
    )


# ==========================================================
# PROJEKT BACKUP
# ==========================================================

def backup_project():

    log(
        "Sichere Projektdateien..."
    )

    project_backup = (
        BACKUP_DIR /
        "project"
    )

    if project_backup.exists():

        shutil.rmtree(
            project_backup
        )

    project_backup.mkdir(
        parents=True
    )

    excluded = {
        ".git",
        ".env.prod",
        "sich",
        ".update_tmp",
        "update.sh",
        "my-venv",
        "__pycache__",
        ".pytest_cache",
    }

    for source in PROJECT_DIR.iterdir():

        if source.name in excluded:
            continue

        destination = (
            project_backup /
            source.name
        )

        if source.is_dir():

            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "my-venv",
                    ".pytest_cache",
                ),
            )

        else:

            shutil.copy2(
                source,
                destination,
            )

    log(
        "Projekt-Backup erstellt."
    )


def create_backup():

    if BACKUP_DIR.exists():

        shutil.rmtree(
            BACKUP_DIR
        )

    BACKUP_DIR.mkdir(
        parents=True
    )

    backup_project()

    backup_postgres()


# ==========================================================
# GITHUB
# ==========================================================

def check_github_tag(
    version,
):

    log(
        f"Prüfe GitHub Tag {version}..."
    )

    result = subprocess.run(
        [
            "git",
            "ls-remote",
            "--exit-code",
            "--tags",
            REPO_URL,
            f"refs/tags/{version}",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:

        raise RuntimeError(
            f"GitHub Tag {version} "
            "nicht gefunden."
        )

    log(
        f"GitHub Tag {version} gefunden."
    )


def download_version(
    version,
):

    log(
        f"Lade Version {version}..."
    )

    if TMP_DIR.exists():

        shutil.rmtree(
            TMP_DIR
        )

    run_command(
        [
            "git",
            "clone",
            "--branch",
            version,
            "--depth",
            "1",
            REPO_URL,
            str(TMP_DIR),
        ]
    )

    log(
        f"Version {version} geladen."
    )


# ==========================================================
# PROJEKT AKTUALISIEREN
# ==========================================================

def replace_project():

    log(
        "Aktualisiere Projektdateien..."
    )

    excluded = {
        ".git",
        ".env.prod",
        "sich",
        ".update_tmp",
        "update.sh",
        "nginx",
        "my-venv",
        "__pycache__",
        ".pytest_cache",
    }

    current_names = {
        item.name
        for item in PROJECT_DIR.iterdir()
    }

    new_names = {
        item.name
        for item in TMP_DIR.iterdir()
    }

    # Nicht mehr vorhandene Dateien entfernen.

    for current in PROJECT_DIR.iterdir():

        if current.name in excluded:
            continue

        if current.name not in new_names:

            if current.is_dir():

                shutil.rmtree(
                    current
                )

            else:

                current.unlink()

    # Neue Dateien kopieren.

    for source in TMP_DIR.iterdir():

        if source.name in excluded:
            continue

        destination = (
            PROJECT_DIR /
            source.name
        )

        if destination.exists():

            if destination.is_dir():

                shutil.rmtree(
                    destination
                )

            else:

                destination.unlink()

        if source.is_dir():

            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "my-venv",
                    ".pytest_cache",
                ),
            )

        else:

            shutil.copy2(
                source,
                destination,
            )

    log(
        "Projektdateien aktualisiert."
    )


# ==========================================================
# DOCKER IMAGE BUILD
# ==========================================================

def build_app():

    log(
        "Baue App-Image..."
    )

    image, logs = (
        docker_client.images.build(
            path=str(PROJECT_DIR),
            tag=APP_IMAGE,
            rm=True,
            pull=False,
        )
    )

    for entry in logs:

        if not isinstance(
            entry,
            dict,
        ):
            continue

        stream = entry.get(
            "stream"
        )

        if stream:

            print(
                stream,
                end="",
                flush=True,
            )

        error = entry.get(
            "error"
        )

        if error:

            raise RuntimeError(
                error
            )

    log(
        "App-Image erfolgreich gebaut."
    )

    return image


# ==========================================================
# APP CONTAINER KONFIGURATION
# ==========================================================

def extract_container_config(
    container,
):
    """
    Liest die bestehende Konfiguration
    des App-Containers.

    Wichtig:
    Mounts werden NICHT mehr aus
    HostConfig["Binds"] zusammengebaut.

    Stattdessen verwenden wir die von Docker
    bereits aufgelösten Mount-Informationen.
    """

    attrs = container.attrs

    config = attrs.get(
        "Config",
        {}
    )

    host_config = attrs.get(
        "HostConfig",
        {}
    )

    environment = config.get(
        "Env"
    ) or []

    command = config.get(
        "Cmd"
    )

    entrypoint = config.get(
        "Entrypoint"
    )

    working_dir = config.get(
        "WorkingDir"
    ) or None

    user = config.get(
        "User"
    ) or None

    hostname = config.get(
        "Hostname"
    ) or None

    labels = config.get(
        "Labels"
    ) or {}

    mounts = []

    for mount in (
        attrs.get("Mounts") or []
    ):

        mount_type = mount.get(
            "Type"
        )

        source = mount.get(
            "Source"
        )

        name = mount.get(
            "Name"
        )

        destination = mount.get(
            "Destination"
        )

        rw = mount.get(
            "RW",
            True,
        )

        if not destination:
            continue

        if mount_type == "volume":

            if not name:
                continue

            mounts.append({
                "type": "volume",
                "source": name,
                "target": destination,
                "read_only": not rw,
            })

        elif mount_type == "bind":

            if not source:
                continue

            mounts.append({
                "type": "bind",
                "source": source,
                "target": destination,
                "read_only": not rw,
            })

    ports = {}

    port_bindings = (
        host_config.get(
            "PortBindings"
        ) or {}
    )

    for container_port, bindings in (
        port_bindings.items()
    ):

        if not bindings:
            continue

        binding = bindings[0]

        host_ip = (
            binding.get(
                "HostIp"
            )
            or ""
        )

        host_port = (
            binding.get(
                "HostPort"
            )
        )

        if host_ip:

            ports[container_port] = (
                host_ip,
                host_port,
            )

        else:

            ports[container_port] = (
                host_port
            )

    restart_policy = (
        host_config.get(
            "RestartPolicy"
        )
        or {}
    )

    network_mode = (
        host_config.get(
            "NetworkMode"
        )
    )

    return {
        "environment": environment,
        "command": command,
        "entrypoint": entrypoint,
        "working_dir": working_dir,
        "user": user,
        "hostname": hostname,
        "labels": labels,
        "mounts": mounts,
        "ports": ports,
        "restart_policy": restart_policy,
        "network_mode": network_mode,
    }


# ==========================================================
# APP CONTAINER NEU ERSTELLEN
# ==========================================================

def recreate_app(
    old_container,
    image,
):

    log(
        f"Erstelle {APP_CONTAINER} neu..."
    )

    saved = extract_container_config(
        old_container
    )

    # Netzwerke merken.

    networks = []

    network_settings = (
        old_container.attrs
        .get("NetworkSettings", {})
        .get("Networks", {})
    )

    for network_name in network_settings:

        if network_name:

            networks.append(
                network_name
            )

    # Alten Container stoppen.

    old_container.reload()

    if old_container.status == "running":

        log(
            f"Stoppe {APP_CONTAINER}..."
        )

        old_container.stop(
            timeout=30
        )

    # Container entfernen.
    #
    # volumes=False ist absichtlich wichtig:
    # Named Volumes dürfen NICHT gelöscht werden.

    old_container.remove(
        v=False
    )

    log(
        f"{APP_CONTAINER} entfernt."
    )

    # Volumes für Docker SDK vorbereiten.

    volume_config = {}

    for mount in saved["mounts"]:

        if mount["type"] == "volume":

            volume_config[
                mount["target"]
            ] = {
                "bind": mount["source"],
                "mode": (
                    "ro"
                    if mount["read_only"]
                    else "rw"
                ),
            }

        elif mount["type"] == "bind":

            volume_config[
                mount["target"]
            ] = {
                "bind": mount["source"],
                "mode": (
                    "ro"
                    if mount["read_only"]
                    else "rw"
                ),
            }

    kwargs = {
        "image": image.id,
        "name": APP_CONTAINER,
        "environment": saved[
            "environment"
        ],
        "command": saved[
            "command"
        ],
        "entrypoint": saved[
            "entrypoint"
        ],
        "working_dir": saved[
            "working_dir"
        ],
        "user": saved[
            "user"
        ],
        "hostname": saved[
            "hostname"
        ],
        "labels": saved[
            "labels"
        ],
        "volumes": volume_config,
        "ports": (
            saved["ports"]
            or None
        ),
        "detach": True,
    }

    restart_policy = saved[
        "restart_policy"
    ]

    if restart_policy:

        kwargs[
            "restart_policy"
        ] = restart_policy

    network_mode = saved[
        "network_mode"
    ]

    if (
        network_mode
        and network_mode != "default"
    ):

        kwargs[
            "network_mode"
        ] = network_mode

    # Container erzeugen.

    new_container = (
        docker_client.containers.create(
            **kwargs
        )
    )

    # Netzwerke wieder verbinden.
    #
    # Nur notwendig, wenn network_mode nicht
    # host/none/etc. verwendet wird.

    if (
        not network_mode
        or network_mode == "default"
    ):

        for network_name in networks:

            try:

                network = (
                    docker_client.networks.get(
                        network_name
                    )
                )

                network.connect(
                    new_container
                )

            except Exception as exc:

                log(
                    f"Warnung: Netzwerk "
                    f"{network_name} konnte "
                    f"nicht verbunden werden: "
                    f"{exc}"
                )

    new_container.start()

    log(
        f"{APP_CONTAINER} neu erstellt "
        "und gestartet."
    )

    return new_container


# ==========================================================
# APP LOGS
# ==========================================================

def get_container_logs(
    container_name,
    lines=150,
):

    try:

        container = get_container(
            container_name
        )

        output = container.logs(
            tail=lines
        )

        return output.decode(
            "utf-8",
            errors="replace",
        )

    except Exception as exc:

        return (
            "Logs konnten nicht gelesen "
            f"werden: {exc}"
        )


# ==========================================================
# APP HEALTHCHECK
# ==========================================================

def check_app_http():

    log(
        "Prüfe Django-App direkt..."
    )

    # Wichtig:
    #
    # Der Check geht NICHT über
    # https://localhost.
    #
    # Dadurch ist Nginx komplett aus
    # dem Update-Check herausgenommen.

    url = (
        f"http://{APP_CONTAINER}:"
        f"{APP_PORT}"
        f"{APP_HEALTH_PATH}"
    )

    log(
        f"Healthcheck: {url}"
    )

    for attempt in range(1, 31):

        try:

            request = Request(
                url,
                method="GET",
            )

            with urlopen(
                request,
                timeout=5,
            ) as response:

                status_code = (
                    response.status
                )

            if status_code in (
                200,
                301,
                302,
                403,
                404,
            ):

                log(
                    "Django-App antwortet."
                )

                log(
                    f"HTTP Status: "
                    f"{status_code}"
                )

                return True

            log(
                f"Django antwortet mit "
                f"HTTP {status_code}."
            )

        except Exception as exc:

            log(
                f"App noch nicht bereit "
                f"({attempt}/30): {exc}"
            )

        time.sleep(2)

    log(
        "Django-App antwortet nicht."
    )

    return False


# ==========================================================
# APP DOCKER HEALTHCHECK
# ==========================================================

def check_container_state():

    container = get_container(
        APP_CONTAINER
    )

    container.reload()

    if container.status != "running":

        logs = get_container_logs(
            APP_CONTAINER,
            100,
        )

        raise RuntimeError(
            "django-app läuft nicht.\n\n"
            f"{logs}"
        )

    # Falls Docker selbst einen HEALTHCHECK
    # definiert, berücksichtigen wir diesen.

    health = (
        container.attrs
        .get("State", {})
        .get("Health")
    )

    if health:

        health_status = health.get(
            "Status"
        )

        log(
            f"Docker Health Status: "
            f"{health_status}"
        )

        if health_status == "unhealthy":

            logs = get_container_logs(
                APP_CONTAINER,
                100,
            )

            raise RuntimeError(
                "django-app ist "
                "unhealthy.\n\n"
                f"{logs}"
            )

    return True


# ==========================================================
# PROJEKT RESTORE
# ==========================================================

def restore_project():

    project_backup = (
        BACKUP_DIR /
        "project"
    )

    if not project_backup.exists():

        log(
            "WARNUNG: Kein Projekt-Backup gefunden."
        )

        return

    log(
        "Stelle Projektdateien "
        "aus Backup wieder her..."
    )

    excluded = {
        ".git",
        ".env.prod",
        "sich",
        ".update_tmp",
        "update.sh",
        "my-venv",
        "__pycache__",
        ".pytest_cache",
    }

    current_names = {
        item.name
        for item in PROJECT_DIR.iterdir()
    }

    backup_names = {
        item.name
        for item in project_backup.iterdir()
    }

    for current in PROJECT_DIR.iterdir():

        if current.name in excluded:
            continue

        if current.name not in backup_names:

            if current.is_dir():

                shutil.rmtree(
                    current
                )

            else:

                current.unlink()

    for source in project_backup.iterdir():

        if source.name in excluded:
            continue

        destination = (
            PROJECT_DIR /
            source.name
        )

        if destination.exists():

            if destination.is_dir():

                shutil.rmtree(
                    destination
                )

            else:

                destination.unlink()

        if source.is_dir():

            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "my-venv",
                    ".pytest_cache",
                ),
            )

        else:

            shutil.copy2(
                source,
                destination,
            )

    log(
        "Projektdateien wiederhergestellt."
    )


# ==========================================================
# ROLLBACK APP
# ==========================================================

def rollback_app(
    old_image_id,
    old_container_config,
):

    if not old_image_id:

        log(
            "Kein altes App-Image für "
            "Rollback vorhanden."
        )

        return

    log(
        "Starte App-Rollback..."
    )

    try:

        try:

            current = get_container(
                APP_CONTAINER
            )

            current.reload()

            if current.status == "running":

                current.stop(
                    timeout=30
                )

            current.remove(
                v=False
            )

        except Exception as exc:

            log(
                f"Alter App-Container "
                f"konnte beim Rollback nicht "
                f"entfernt werden: {exc}"
            )

        # Alte Container-Konfiguration
        # wiederherstellen.

        environment = (
            old_container_config[
                "environment"
            ]
        )

        command = (
            old_container_config[
                "command"
            ]
        )

        entrypoint = (
            old_container_config[
                "entrypoint"
            ]
        )

        working_dir = (
            old_container_config[
                "working_dir"
            ]
        )

        user = (
            old_container_config[
                "user"
            ]
        )

        hostname = (
            old_container_config[
                "hostname"
            ]
        )

        labels = (
            old_container_config[
                "labels"
            ]
        )

        volumes = {}

        for mount in (
            old_container_config[
                "mounts"
            ]
        ):

            volumes[
                mount["target"]
            ] = {
                "bind": mount["source"],
                "mode": (
                    "ro"
                    if mount["read_only"]
                    else "rw"
                ),
            }

        ports = (
            old_container_config[
                "ports"
            ]
        )

        kwargs = {
            "image": old_image_id,
            "name": APP_CONTAINER,
            "environment": environment,
            "command": command,
            "entrypoint": entrypoint,
            "working_dir": working_dir,
            "user": user,
            "hostname": hostname,
            "labels": labels,
            "volumes": volumes,
            "ports": ports or None,
            "detach": True,
        }

        restart_policy = (
            old_container_config[
                "restart_policy"
            ]
        )

        if restart_policy:

            kwargs[
                "restart_policy"
            ] = restart_policy

        network_mode = (
            old_container_config[
                "network_mode"
            ]
        )

        if (
            network_mode
            and network_mode != "default"
        ):

            kwargs[
                "network_mode"
            ] = network_mode

        old_container = (
            docker_client.containers.create(
                **kwargs
            )
        )

        # Netzwerke wiederherstellen.

        if (
            not network_mode
            or network_mode == "default"
        ):

            for network_name in (
                old_container_config[
                    "networks"
                ]
            ):

                try:

                    network = (
                        docker_client
                        .networks
                        .get(
                            network_name
                        )
                    )

                    network.connect(
                        old_container
                    )

                except Exception as exc:

                    log(
                        f"Rollback-Netzwerk "
                        f"{network_name}: "
                        f"{exc}"
                    )

        old_container.start()

        log(
            "App-Rollback erfolgreich."
        )

    except Exception as exc:

        log(
            f"APP-ROLLBACK FEHLGESCHLAGEN: "
            f"{exc}"
        )

        raise


# ==========================================================
# ROLLBACK
# ==========================================================

def rollback(
    version,
    error,
    old_image_id=None,
    old_container_config=None,
):

    log(
        "======================================"
    )

    log(
        " UPDATE FEHLGESCHLAGEN"
    )

    log(
        "======================================"
    )

    log(
        f"Fehler: {error}"
    )

    try:

        restore_project()

    except Exception as exc:

        log(
            f"Fehler beim Wiederherstellen "
            f"der Projektdateien: {exc}"
        )

    if (
        old_image_id
        and old_container_config
    ):

        try:

            rollback_app(
                old_image_id,
                old_container_config,
            )

        except Exception as exc:

            log(
                f"App-Rollback fehlgeschlagen: "
                f"{exc}"
            )

    else:

        log(
            "Kein vollständiges App-Rollback "
            "möglich."
        )

    # Nginx wird ABSICHTLICH nicht angefasst.
    #
    # PostgreSQL wird ABSICHTLICH nicht angefasst.

    log(
        "Nginx bleibt unverändert."
    )

    log(
        "PostgreSQL bleibt unverändert."
    )

    log(
        "Rollback abgeschlossen."
    )


# ==========================================================
# UPDATE
# ==========================================================

def run_update(
    version,
):

    old_image_id = None
    old_container_config = None

    try:

        write_status(
            "running",
            version,
            "",
        )

        log(
            "======================================"
        )

        log(
            " Starte Update"
        )

        log(
            "======================================"
        )

        log(
            f"Version: {version}"
        )

        # --------------------------------------------------
        # Docker
        # --------------------------------------------------

        log(
            "Prüfe Docker API..."
        )

        docker_client.ping()

        log(
            "Docker API erreichbar."
        )

        # --------------------------------------------------
        # Container
        # --------------------------------------------------

        postgres = get_container(
            POSTGRES_CONTAINER
        )

        app = get_container(
            APP_CONTAINER
        )

        log(
            "Benötigte Container vorhanden."
        )

        # --------------------------------------------------
        # Alten App-Zustand sichern
        # --------------------------------------------------

        log(
            "Sichere aktuelle App-Konfiguration..."
        )

        app.reload()

        old_image_id = (
            app.image.id
        )

        old_container_config = (
            extract_container_config(
                app
            )
        )

        # Netzwerke ergänzen.

        old_container_config[
            "networks"
        ] = list(
            (
                app.attrs
                .get("NetworkSettings", {})
                .get("Networks", {})
                or {}
            ).keys()
        )

        log(
            f"Altes App-Image: "
            f"{old_image_id}"
        )

        # --------------------------------------------------
        # PostgreSQL
        # --------------------------------------------------

        postgres.reload()

        if postgres.status != "running":

            raise RuntimeError(
                "PostgreSQL läuft nicht."
            )

        log(
            "PostgreSQL läuft."
        )

        # --------------------------------------------------
        # Backup
        # --------------------------------------------------

        log(
            "[1/7] Erstelle Backup..."
        )

        create_backup()

        # --------------------------------------------------
        # GitHub
        # --------------------------------------------------

        log(
            "[2/7] Prüfe GitHub-Version..."
        )

        check_github_tag(
            version
        )

        # --------------------------------------------------
        # Download
        # --------------------------------------------------

        log(
            "[3/7] Lade Version..."
        )

        download_version(
            version
        )

        # --------------------------------------------------
        # Projekt aktualisieren
        # --------------------------------------------------

        log(
            "[4/7] Aktualisiere Projekt..."
        )

        replace_project()

        # TMP nicht löschen, bevor der Build fertig ist.

        # --------------------------------------------------
        # App Image bauen
        # --------------------------------------------------

        log(
            "[5/7] Baue App-Image..."
        )

        new_image = build_app()

        # --------------------------------------------------
        # App Container neu erstellen
        # --------------------------------------------------

        log(
            "[6/7] Aktualisiere django-app..."
        )

        new_container = recreate_app(
            app,
            new_image,
        )

        # --------------------------------------------------
        # TMP entfernen
        # --------------------------------------------------

        if TMP_DIR.exists():

            shutil.rmtree(
                TMP_DIR
            )

        # --------------------------------------------------
        # App prüfen
        # --------------------------------------------------

        if not wait_for_container(
            APP_CONTAINER,
            60,
        ):

            logs = get_container_logs(
                APP_CONTAINER,
                150,
            )

            raise RuntimeError(
                "django-app läuft nicht.\n\n"
                f"{logs}"
            )

        check_container_state()

        # --------------------------------------------------
        # Django Healthcheck
        # --------------------------------------------------

        log(
            "[7/7] Prüfe Django..."
        )

        if not check_app_http():

            logs = get_container_logs(
                APP_CONTAINER,
                150,
            )

            raise RuntimeError(
                "Django antwortet nicht.\n\n"
                f"{logs}"
            )

        # --------------------------------------------------
        # Erfolg
        # --------------------------------------------------

        write_status(
            "success",
            version,
            "",
        )

        log(
            "======================================"
        )

        log(
            " UPDATE ERFOLGREICH"
        )

        log(
            "======================================"
        )

    except Exception as exc:

        log(
            f"UPDATE FEHLGESCHLAGEN: {exc}"
        )

        try:

            rollback(
                version,
                exc,
                old_image_id,
                old_container_config,
            )

        except Exception as rollback_error:

            log(
                "Rollback-Fehler: "
                f"{rollback_error}"
            )

        write_status(
            "failed",
            version,
            str(exc),
        )

    finally:

        try:

            if TMP_DIR.exists():

                shutil.rmtree(
                    TMP_DIR
                )

        except Exception:
            pass