"""
Flask wrapper for the LinkedIn publisher.

POST /publish  — triggers publisher.main() in a background thread.
               Returns 202 immediately; caller doesn't need to wait.
               Returns 409 if a publish run is already in progress.
GET  /health   — returns status and whether a run is currently active.

Auth: pass PUBLISH_TOKEN (env) as a form field named 'token' in the POST body.
"""

import os
import subprocess
import threading
from flask import Flask, request, jsonify
import publisher

app = Flask(__name__)

PUBLISH_TOKEN  = os.environ.get("PUBLISH_TOKEN", "")
PUBLISH_TIMEOUT = int(os.environ.get("PUBLISH_TIMEOUT", "720"))  # seconds; 0 = no limit


def _kill_browser():
    """Kill any lingering Chrome/ChromeDriver processes."""
    try:
        subprocess.run(["pkill", "-f", "chromium"], capture_output=True)
        subprocess.run(["pkill", "-f", "chromedriver"], capture_output=True)
    except Exception:
        pass


_lock        = threading.Lock()
_running     = False
_last_result = None   # "ok" | "error: <message>"


def _run_publisher():
    global _running, _last_result

    def _on_timeout():
        global _running, _last_result
        print(f"[app] Publisher timed out after {PUBLISH_TIMEOUT}s — killing browser")
        _kill_browser()
        _last_result = f"error: timed out after {PUBLISH_TIMEOUT}s"
        with _lock:
            _running = False

    watchdog = None
    if PUBLISH_TIMEOUT > 0:
        watchdog = threading.Timer(PUBLISH_TIMEOUT, _on_timeout)
        watchdog.daemon = True
        watchdog.start()

    try:
        publisher.main()
        _last_result = "ok"
    except Exception as e:
        _last_result = f"error: {e}"
        print(f"[app] Publisher error: {e}")
    finally:
        if watchdog:
            watchdog.cancel()
        with _lock:
            _running = False


@app.route("/publish", methods=["POST"])
def publish():
    global _running

    # Simple token auth
    token = request.form.get("token") or request.headers.get("X-Publish-Token", "")
    if PUBLISH_TOKEN and token != PUBLISH_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    with _lock:
        if _running:
            return jsonify({"status": "already_running"}), 409
        _running = True

    t = threading.Thread(target=_run_publisher, daemon=True)
    t.start()
    return jsonify({"status": "triggered"}), 202


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":      "ok",
        "running":     _running,
        "last_result": _last_result,
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
