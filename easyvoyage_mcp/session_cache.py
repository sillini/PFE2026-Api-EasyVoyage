"""
easyvoyage_mcp/session_cache.py
================================
Cache JWT cote MCP — serveur HTTP partage entre processus.

CORRECTION :
  Les differents MCP servers tournent en processus separes et ne
  peuvent pas partager une variable Python. Le cache doit donc etre
  accede EXCLUSIVEMENT via HTTP au serveur Flask central.
"""
import os
import threading
import time
import httpx
from typing import Optional
from flask import Flask, request, jsonify

CACHE_PORT = int(os.getenv("MCP_SESSION_CACHE_PORT", "9100"))
CACHE_URL = f"http://127.0.0.1:{CACHE_PORT}"
TTL_SECONDS = 600
CLEANUP_INTERVAL = 60

# Dict local au process du SERVEUR cache (pas accessible aux autres)
_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def _cleanup_expired():
    while True:
        time.sleep(CLEANUP_INTERVAL)
        now = time.time()
        with _lock:
            expired = [k for k, (_, exp) in _cache.items() if exp < now]
            for k in expired:
                _cache.pop(k, None)


# ══════════════════════════════════════════════════════════
#  API CLIENT (utilisee par les tools MCP)
#  → fait un appel HTTP au serveur cache
# ══════════════════════════════════════════════════════════

def get_jwt(session_id: str) -> Optional[str]:
    """Recupere le JWT via HTTP au serveur cache."""
    if not session_id:
        return None
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{CACHE_URL}/get_session/{session_id}")
        if r.status_code == 200:
            data = r.json()
            return data.get("jwt_token")
        return None
    except Exception as e:
        print(f"[CACHE CLIENT] Error get_jwt({session_id}): {e}")
        return None


def register_jwt(session_id: str, jwt: str) -> bool:
    """Enregistre via HTTP au serveur cache."""
    if not session_id or not jwt:
        return False
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.post(
                f"{CACHE_URL}/register_session",
                json={"session_id": session_id, "jwt_token": jwt},
            )
        return r.status_code == 200
    except Exception as e:
        print(f"[CACHE CLIENT] Error register_jwt: {e}")
        return False


# ══════════════════════════════════════════════════════════
#  SERVEUR HTTP — tourne UNE SEULE FOIS sur le port 9100
# ══════════════════════════════════════════════════════════

app = Flask("mcp_session_cache")


@app.route("/register_session", methods=["POST"])
def register_session():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    jwt_token = data.get("jwt_token")

    if not session_id or not jwt_token:
        return jsonify({"error": "session_id et jwt_token requis"}), 400

    with _lock:
        _cache[session_id] = (jwt_token, time.time() + TTL_SECONDS)

    print(f"[SESSION CACHE] Registered {session_id} (jwt len={len(jwt_token)})")
    return jsonify({"ok": True, "session_id": session_id})


@app.route("/get_session/<session_id>", methods=["GET"])
def get_session(session_id):
    """Retourne le JWT associe a un session_id."""
    with _lock:
        entry = _cache.get(session_id)
        if not entry:
            return jsonify({"error": "not found"}), 404
        jwt_token, expires_at = entry
        if time.time() > expires_at:
            _cache.pop(session_id, None)
            return jsonify({"error": "expired"}), 404
    return jsonify({"ok": True, "session_id": session_id, "jwt_token": jwt_token})


@app.route("/health", methods=["GET"])
def health():
    with _lock:
        n = len(_cache)
    return jsonify({"ok": True, "sessions": n})


_server_started = False
_server_lock = threading.Lock()


def _is_cache_alive() -> bool:
    """Teste si un serveur cache tourne deja sur le port 9100."""
    try:
        with httpx.Client(timeout=1.0) as c:
            r = c.get(f"{CACHE_URL}/health")
        return r.status_code == 200
    except Exception:
        return False


def start_cache_server():
    """Lance le serveur Flask. Idempotent — ne demarre qu'une fois."""
    global _server_started
    with _server_lock:
        if _server_started:
            return
        # Si un autre process a deja lance le cache, on se contente d'etre client
        if _is_cache_alive():
            print(f"[SESSION CACHE] Serveur deja actif sur {CACHE_URL} (autre process)")
            _server_started = True
            return
        _server_started = True

    threading.Thread(
        target=_cleanup_expired,
        daemon=True,
        name="session-cache-cleanup",
    ).start()

    def _run():
        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        try:
            app.run(host="127.0.0.1", port=CACHE_PORT, debug=False, use_reloader=False)
        except OSError as e:
            print(f"[SESSION CACHE] Port {CACHE_PORT} deja pris - on passe en mode client")

    t = threading.Thread(target=_run, daemon=True, name="session-cache-http")
    t.start()
    time.sleep(0.5)
    print(f"[SESSION CACHE] Serveur démarré sur {CACHE_URL}")