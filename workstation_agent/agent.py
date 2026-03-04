"""
PLM Lite V1.1.0 — Workstation Agent
Runs on localhost:27370 on each NX workstation.
Acts as a bridge between NX Open hooks and the PLM server.

Start: python agent.py
Required env vars:
  PLM_BASE_URL  — e.g. http://192.168.1.37:8070
  PLM_JWT       — JWT token from PLM login (set by plmopen:// URI handler or manually)
"""
import os
import uuid
import socket
from datetime import datetime

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

PLM_BASE_URL = os.environ.get("PLM_BASE_URL", "http://localhost:8070")
PLM_JWT      = os.environ.get("PLM_JWT", "")
SESSION_ID   = str(uuid.uuid4())
STATION_NAME = socket.gethostname()


def _plm_headers():
    return {
        "Authorization": f"Bearer {PLM_JWT}",
        "Content-Type": "application/json",
    }


def _plm(method, path, **kwargs):
    """Make a request to the PLM server."""
    url = PLM_BASE_URL.strip().rstrip("/") + path
    resp = requests.request(method, url, headers=_plm_headers(), timeout=10, **kwargs)
    resp.raise_for_status()
    return resp.json()


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({"status": "ok", "session_id": SESSION_ID, "station": STATION_NAME})


# ── Ping / keep-alive ─────────────────────────────────────────────────────────

@app.post("/ping")
def ping():
    """
    Called by NX hook on startup and periodically.
    Registers this session with the PLM server.
    Body: {nx_version, user_id}
    """
    body       = request.get_json(silent=True) or {}
    nx_version = body.get("nx_version", "unknown")
    user_id    = body.get("user_id")

    try:
        _plm("POST", "/api/cache/ping", json={
            "session_id":   SESSION_ID,
            "nx_version":   nx_version,
            "station_name": STATION_NAME,
            "user_id":      user_id,
        })
    except Exception as e:
        # Non-fatal — PLM server may be unreachable
        app.logger.warning(f"Ping failed: {e}")

    return jsonify({"ok": True, "session_id": SESSION_ID})


# ── Open file ─────────────────────────────────────────────────────────────────

@app.post("/open")
def open_file():
    """
    Called by NX hook or plmopen:// URI handler.
    Body: {part_number, user_id}
    Returns: {path: <stored_path on network share>}
    """
    body        = request.get_json(silent=True) or {}
    part_number = body.get("part_number", "")
    user_id     = body.get("user_id")

    if not part_number:
        return jsonify({"error": "part_number required"}), 400

    try:
        # Search for part
        parts = _plm("GET", f"/api/parts?pn={part_number}")
        if not parts:
            return jsonify({"error": f"Part not found: {part_number}"}), 404

        part_id = parts[0]["id"]

        # Get documents for part
        docs = _plm("GET", f"/api/parts/{part_id}/documents")
        # Prefer CAD files
        cad_exts = {".prt", ".asm", ".sldprt", ".sldasm", ".ipt", ".iam", ".step", ".stp"}
        cad_docs = [d for d in docs if "." + d.get("file_type", "") in cad_exts]

        if not cad_docs and not docs:
            return jsonify({"error": f"No documents found for part {part_number}"}), 404

        doc = cad_docs[0] if cad_docs else docs[0]
        return jsonify({"path": doc["stored_path"], "filename": doc["filename"], "part_id": part_id})

    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Checkout ──────────────────────────────────────────────────────────────────

@app.post("/checkout")
def checkout():
    """
    Forward checkout request to PLM server.
    Body: {part_id} or {part_number}
    """
    body    = request.get_json(silent=True) or {}
    part_id = body.get("part_id")

    if not part_id and body.get("part_number"):
        try:
            parts = _plm("GET", f"/api/parts?pn={body['part_number']}")
            if parts:
                part_id = parts[0]["id"]
        except Exception:
            pass

    if not part_id:
        return jsonify({"error": "part_id required"}), 400

    try:
        result = _plm("POST", f"/api/parts/{part_id}/checkout", json={
            "station": STATION_NAME
        })
        return jsonify(result)
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500


# ── Checkin ───────────────────────────────────────────────────────────────────

@app.post("/checkin")
def checkin():
    """
    Forward checkin request to PLM server.
    Body: {part_id} or {part_number}
    """
    body    = request.get_json(silent=True) or {}
    part_id = body.get("part_id")

    if not part_id and body.get("part_number"):
        try:
            parts = _plm("GET", f"/api/parts?pn={body['part_number']}")
            if parts:
                part_id = parts[0]["id"]
        except Exception:
            pass

    if not part_id:
        return jsonify({"error": "part_id required"}), 400

    try:
        result = _plm("POST", f"/api/parts/{part_id}/checkin")
        return jsonify(result)
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"PLM Workstation Agent starting")
    print(f"  Session : {SESSION_ID}")
    print(f"  Station : {STATION_NAME}")
    print(f"  PLM URL : {PLM_BASE_URL}")
    print(f"  Listening on 127.0.0.1:27370")
    app.run(host="127.0.0.1", port=27370, debug=False)
