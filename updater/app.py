import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request

from update import run_update


app = Flask(__name__)


UPDATER_SECRET = os.environ.get("UPDATER_SECRET", "")
STATUS_FILE = Path(
    os.environ.get(
        "UPDATER_STATUS_FILE",
        "/var/log/django/update-status.json",
    )
)


def check_secret():
    if not UPDATER_SECRET:
        return False

    return (
        request.headers.get("X-Updater-Secret", "")
        == UPDATER_SECRET
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
        import json

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


@app.get("/status")
def status():

    if not check_secret():
        return jsonify({
            "error": "unauthorized"
        }), 401

    return jsonify(read_status())


@app.post("/update")
def update():

    if not check_secret():
        return jsonify({
            "error": "unauthorized"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    version = str(
        data.get("version", "")
    ).strip()

    if not version:
        return jsonify({
            "error": "Keine Version angegeben."
        }), 400

    if not version.startswith("v"):
        version = f"v{version}"

    current = read_status()

    if current.get("status") == "running":
        return jsonify({
            "status": "running",
            "version": current.get(
                "version",
                "",
            ),
            "message": (
                "Ein Update läuft bereits."
            ),
        }), 409

    thread = threading.Thread(
        target=run_update,
        args=(version,),
        daemon=True,
    )

    thread.start()

    return jsonify({
        "status": "running",
        "version": version,
    }), 202


@app.get("/health")
def health():
    return jsonify({
        "status": "ok"
    })


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "UPDATER_PORT",
            "9000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
    )

