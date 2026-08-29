#!/bin/bash

set -Eeuo pipefail

# ==========================================================
# Zeiterfassung Update Script
# ==========================================================

REPO_URL="https://github.com/Niklwas/Zeiterfassung.git"

BACKUP_DIR="sich"
TMP_DIR=".update_tmp"

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VERSION="${1:-}"

LOG_FILE="/var/log/django/update.log"

COMPOSE=(docker compose -f "$CURRENT_DIR/docker-compose.yml")


# ==========================================================
# Logging
# ==========================================================

mkdir -p "$(dirname "$LOG_FILE")"
rm "$LOG_FILE"
touch "$LOG_FILE"

exec > >(tee -a "$LOG_FILE") 2>&1


# ==========================================================
# Funktionen
# ==========================================================

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}


log() {
    echo "[$(timestamp)] $*"
}


cleanup() {
    rm -rf "$CURRENT_DIR/$TMP_DIR"
}


container_running() {
    local container="$1"

    docker inspect \
        --format '{{.State.Running}}' \
        "$container" \
        2>/dev/null \
        | grep -q "true"
}


# ==========================================================
# Rollback
# ==========================================================

rollback() {

    local exit_code=$?

    trap - ERR

    echo
    echo "======================================"
    echo " UPDATE FEHLGESCHLAGEN"
    echo "======================================"
    echo

    log "Exit-Code: $exit_code"

    cd "$CURRENT_DIR"

    # ------------------------------------------------------
    # Temporäre Dateien entfernen
    # ------------------------------------------------------

    rm -rf "$TMP_DIR"


    # ------------------------------------------------------
    # Projektdateien wiederherstellen
    # ------------------------------------------------------

    if [ -d "$BACKUP_DIR/project" ]; then

        log "Stelle Projektdateien aus Backup wieder her..."

        rsync -a --delete \
            --exclude=".git/" \
            --exclude=".env.prod" \
            --exclude="sich/" \
            --exclude=".update_tmp/" \
            --exclude="update.sh" \
            "$BACKUP_DIR/project/" \
            "$CURRENT_DIR/"

        log "Projektdateien wiederhergestellt."

    else

        log "WARNUNG: Kein Projekt-Backup gefunden!"

    fi


    # ------------------------------------------------------
    # App und Nginx aus Backup neu bauen
    # ------------------------------------------------------

    log "Baue App und Nginx aus dem Backup..."

    if "${COMPOSE[@]}" build app; then

        log "Backup-Images erfolgreich gebaut."

    else

        log "FEHLER: Backup-Images konnten nicht gebaut werden."

    fi


    # ------------------------------------------------------
    # App und Nginx starten
    #
    # WICHTIG:
    # --no-deps verhindert, dass db/updater angefasst werden.
    # --force-recreate stellt die Container sauber neu her.
    # ------------------------------------------------------

    log "Starte Appaus dem Backup..."

    if "${COMPOSE[@]}" up -d \
        --force-recreate \
        --no-deps \
        app; then

        log "App und Nginx wurden aus dem Backup gestartet."

    else

        log "FEHLER: App/Nginx konnten nicht gestartet werden."

    fi


    # ------------------------------------------------------
    # Status
    # ------------------------------------------------------

    echo
    log "Aktueller Docker-Status:"

    "${COMPOSE[@]}" ps || true


    echo
    echo "======================================"
    echo " ROLLBACK ABGESCHLOSSEN"
    echo "======================================"
    echo

    exit "$exit_code"
}


trap rollback ERR
trap cleanup EXIT


# ==========================================================
# Eingabe prüfen
# ==========================================================

if [ -z "$VERSION" ]; then

    echo "Fehler: Keine Version angegeben."
    echo
    echo "Verwendung:"
    echo "  ./update.sh v1.0.260827"

    exit 1

fi


if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]{6}$ ]]; then

    echo "Fehler: Ungültiges Versionsformat: $VERSION"
    echo
    echo "Erwartet wird z.B.:"
    echo "  v1.0.260827"

    exit 1

fi


echo
echo "======================================"
echo " Zeiterfassung Update"
echo "======================================"
echo
echo "Version:     $VERSION"
echo "Verzeichnis: $CURRENT_DIR"
echo "Logdatei:    $LOG_FILE"
echo


# ==========================================================
# Docker Compose
# ==========================================================

log "[1/8] Prüfe Docker..."

docker version

echo

log "Prüfe Docker Compose..."

docker compose version

echo


# ==========================================================
# Bestehende Container prüfen
# ==========================================================

log "Prüfe bestehende Container..."


if ! docker inspect django-postgres >/dev/null 2>&1; then

    echo "FEHLER: django-postgres existiert nicht."
    exit 1

fi


if ! docker inspect django-updater >/dev/null 2>&1; then

    echo "FEHLER: django-updater existiert nicht."
    exit 1

fi


log "PostgreSQL und Updater vorhanden."


# ----------------------------------------------------------
# PostgreSQL muss laufen
# ----------------------------------------------------------

echo

log "Prüfe PostgreSQL..."

if ! container_running django-postgres; then

    echo
    log "FEHLER: django-postgres läuft nicht."
    exit 1

fi

log "PostgreSQL läuft."

echo


# ==========================================================
# Backup
# ==========================================================

log "[2/8] Erstelle Backup..."

rm -rf "$BACKUP_DIR"

mkdir -p "$BACKUP_DIR/project"


# ----------------------------------------------------------
# Projektdateien sichern
# ----------------------------------------------------------

log "Sichere Projektdateien..."

rsync -a \
    --exclude=".git/" \
    --exclude=".env.prod" \
    --exclude="sich/" \
    --exclude=".update_tmp/" \
    --exclude="update.sh" \
    --exclude="docker-compose.yml" \
    "$CURRENT_DIR/" \
    "$BACKUP_DIR/project/"

log "Projekt-Backup erstellt."


# ----------------------------------------------------------
# PostgreSQL sichern
# ----------------------------------------------------------

echo

log "Erstelle PostgreSQL Backup..."

docker exec django-postgres sh -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    > "$BACKUP_DIR/django_backup.sql"

log "Datenbank-Backup erstellt."

echo


# ==========================================================
# GitHub Tag prüfen
# ==========================================================

log "[3/8] Prüfe GitHub-Version..."

git ls-remote \
    --exit-code \
    --tags \
    "$REPO_URL" \
    "refs/tags/$VERSION" \
    > /dev/null

log "GitHub Tag $VERSION gefunden."

echo


# ==========================================================
# GitHub Version herunterladen
# ==========================================================

log "[4/8] Lade Version $VERSION..."

rm -rf "$TMP_DIR"

git clone \
    --branch "$VERSION" \
    --depth 1 \
    "$REPO_URL" \
    "$TMP_DIR"

log "Version $VERSION geladen."

echo


# ==========================================================
# App und Nginx stoppen
# ==========================================================

log "[5/8] Stoppe..."

# WICHTIG:
#
# Hier werden Compose-SERVICE-NAMEN verwendet:
#
# app
# nginx
#
# NICHT:
# django-app
# django-nginx
#
# PostgreSQL (db) und Updater (updater) bleiben laufen.

"${COMPOSE[@]}" stop app

log "App und Nginx gestoppt."

echo


# ==========================================================
# Projektdateien aktualisieren
# ==========================================================

log "[6/8] Aktualisiere Projektdateien..."

rsync -a --delete \
    --exclude=".git/" \
    --exclude=".env.prod" \
    --exclude="sich/" \
    --exclude=".update_tmp/" \
    --exclude="update.sh" \
    --exclude="docker-compose.yml" \
    "$TMP_DIR/" \
    "$CURRENT_DIR/"

rm -rf "$TMP_DIR"

log "Projektdateien aktualisiert."

echo


# ==========================================================
# Docker neu bauen
# ==========================================================

log "Baue App neu..."

"${COMPOSE[@]}" up -d --build app

log "App erfolgreich gebaut."

echo


# ==========================================================
# App und Nginx starten
# ==========================================================

log "Starte App..."

# WICHTIG:
#
# --no-deps:
#   db und updater werden NICHT gestartet/erstellt.
#
# --force-recreate:
#   App und Nginx werden garantiert neu erstellt.
#
# Dadurch entstehen keine Konflikte mit PostgreSQL-Port 5432.

#"${COMPOSE[@]}" up -d \
#    --force-recreate \
#    --no-deps \
#    app
#
#log "App gestartet."
#
#echo


# ==========================================================
# Warten
# ==========================================================

log "Warte auf App..."

sleep 5


# ==========================================================
# Container prüfen
# ==========================================================

log "[7/8] Prüfe Container..."


if ! container_running django-app; then

    echo
    log "FEHLER: django-app läuft nicht."

    echo
    log "Logs von django-app:"

    docker logs \
        --tail=150 \
        django-app \
        || true

    exit 1

fi

log "django-app läuft."


if ! container_running django-nginx; then

    echo
    log "FEHLER: django-nginx läuft nicht."

    echo
    log "Logs von django-nginx:"

    docker logs \
        --tail=150 \
        django-nginx \
        || true

    exit 1

fi

log "django-nginx läuft."


# ----------------------------------------------------------
# PostgreSQL prüfen
# ----------------------------------------------------------

if ! container_running django-postgres; then

    echo
    log "FEHLER: django-postgres läuft nicht."

    exit 1

fi

log "django-postgres läuft."


# ----------------------------------------------------------
# Updater prüfen
# ----------------------------------------------------------

if ! container_running django-updater; then

    echo
    log "FEHLER: django-updater läuft nicht."

    exit 1

fi

log "django-updater läuft."


# ==========================================================
# HTTP-Test
# ==========================================================

log "[8/8] Prüfe Django über HTTPS..."

HTTP_OK=false


for i in {1..20}; do

    HTTP_CODE="$(
        curl \
            -k \
            -s \
            --max-time 5 \
            -o /dev/null \
            -w "%{http_code}" \
            https://localhost/admin/ \
            || true
    )"


    if [[ "$HTTP_CODE" =~ ^(200|301|302|403)$ ]]; then

        HTTP_OK=true

        log "Django antwortet erfolgreich."
        log "HTTP Status: $HTTP_CODE"

        break

    fi


    log "Noch nicht bereit... ($i/20) HTTP=$HTTP_CODE"

    sleep 2

done


if [ "$HTTP_OK" != "true" ]; then

    echo
    log "FEHLER: Django antwortet nicht."

    echo
    log "Logs von django-app:"

    docker logs \
        --tail=150 \
        django-app \
        || true

    echo
    log "Logs von django-nginx:"

    docker logs \
        --tail=150 \
        django-nginx \
        || true

    exit 1

fi


# ==========================================================
# Erfolg
# ==========================================================

trap - ERR
trap - EXIT


echo
echo "======================================"
echo " UPDATE ERFOLGREICH"
echo "======================================"
echo
echo "Installierte Version:"
echo "  $VERSION"
echo
echo "Backup:"
echo "  $CURRENT_DIR/$BACKUP_DIR"
echo
echo "Log:"
echo "  $LOG_FILE"
echo
echo "======================================"
echo

log "Update erfolgreich abgeschlossen."