import os
from collections import deque
from datetime import datetime
from hmac import compare_digest
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

from flask import Flask, g, jsonify, render_template, request
from openai import OpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAIError
from sqlite3 import IntegrityError

import db as traffic_lights_db


def _load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from .env into os.environ (fills missing/empty only)."""
    candidates = []
    if path is not None:
        candidates.append(path)
    else:
        here = Path(__file__).resolve().parent
        candidates.extend([
            here / ".env",
            Path.cwd() / ".env",
            Path("/app/.env"),
        ])

    for env_path in candidates:
        if not env_path.is_file():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and not os.environ.get(key, "").strip():
                os.environ[key] = value
        break


_load_dotenv()

app = Flask(__name__)
traffic_lights_db.init_db()

# Mutable API key for Bearer auth on /api/traffic-light/* (empty = auth disabled)
# Initial value from API_KEY env; changeable from the web UI
DEFAULT_API_KEY = os.environ.get("API_KEY", "secretapikey")
api_key_lock = Lock()
api_key: str = DEFAULT_API_KEY

# Fake traffic-light serial / location ID (exactly 10 digits); changeable from the web UI
_raw_serial = os.environ.get("SERIAL_NUMBER", "4829173056").strip() or "4829173056"
DEFAULT_SERIAL_NUMBER = _raw_serial if _raw_serial.isdigit() and len(_raw_serial) == 10 else "4829173056"
serial_number_lock = Lock()
serial_number: str = DEFAULT_SERIAL_NUMBER

# Local OpenAI-compatible agent (Force Agent Check)
AGENT_FORCE_CHECK_MESSAGE = "Inspect the light"
DEFAULT_AGENT_BASE_URL = "http://127.0.0.1:5050/v1"
DEFAULT_AGENT_API_KEY = "agent-local-key"
DEFAULT_AGENT_ID = "default"
DEFAULT_AGENT_MODEL = "default"


def _agent_base_url() -> str:
    _load_dotenv()
    return (
        os.environ.get("AGENT_BASE_URL", DEFAULT_AGENT_BASE_URL).strip()
        or DEFAULT_AGENT_BASE_URL
    )


def _agent_api_key() -> str:
    _load_dotenv()
    return (
        os.environ.get("AGENT_API_KEY", DEFAULT_AGENT_API_KEY).strip()
        or DEFAULT_AGENT_API_KEY
    )


def _agent_id() -> str:
    _load_dotenv()
    return os.environ.get("AGENT_ID", DEFAULT_AGENT_ID).strip() or DEFAULT_AGENT_ID


def _agent_model() -> str:
    _load_dotenv()
    return (
        os.environ.get("AGENT_MODEL", DEFAULT_AGENT_MODEL).strip()
        or DEFAULT_AGENT_MODEL
    )

# In-memory storage for traffic light state
# color is always one of STATUS_COLORS; persistent locks color changes when True
traffic_light_state = {
    "color": "red",
    "persistent": False,
    "timestamp": datetime.now().isoformat()
}

# Public status colors (persistent failure still reports as "failure")
STATUS_COLORS = ["red", "amber", "green", "failure"]
# Values returned by GET /api/traffic-light/colors (normal settable colors only)
LISTED_COLORS = ["red", "amber", "green"]
# Accepted POST values — failure modes are set via dedicated values, not listed above
VALID_SET_COLORS = ["red", "amber", "green", "failure", "persistent_failure"]

# Live API traffic monitor — ring buffer (in-memory only)
MAX_DEBUG_REQUESTS = 100
MAX_BODY_CHARS = 4000
request_log: deque = deque(maxlen=MAX_DEBUG_REQUESTS)
request_log_lock = Lock()
request_seq = 0

SKIP_DEBUG_PREFIXES = ("/api/debug", "/api/settings")


def _get_api_key() -> str:
    with api_key_lock:
        return api_key


def _set_api_key(new_key: str) -> str:
    global api_key
    with api_key_lock:
        api_key = new_key
        return api_key


def _get_serial_number() -> str:
    with serial_number_lock:
        return serial_number


def _set_serial_number(new_serial: str) -> str:
    global serial_number
    with serial_number_lock:
        serial_number = new_serial
        return serial_number


def _normalize_serial_number(value: object) -> tuple[str | None, str | None]:
    """Return (serial, error). Serial must be exactly 10 digits."""
    if value is None:
        return None, "Missing 'serial_number' field in request body"
    if not isinstance(value, str):
        return None, "'serial_number' must be a string of exactly 10 digits"
    serial = value.strip()
    if not serial.isdigit() or len(serial) != 10:
        return None, "'serial_number' must be exactly 10 digits"
    return serial, None


def _extract_bearer_token() -> str | None:
    auth = request.headers.get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _unauthorized(message: str):
    response = jsonify({"success": False, "error": message})
    response.status_code = 401
    response.headers["WWW-Authenticate"] = 'Bearer realm="traffic-light"'
    return response


def _require_api_key():
    """Enforce Bearer API key on protected API routes when a key is configured."""
    path = request.path
    if not (
        path.startswith("/api/traffic-light")
        or path.startswith("/api/registry")
    ):
        return None

    current_key = _get_api_key()
    if not current_key:
        return None  # auth disabled

    token = _extract_bearer_token()
    if token is None:
        return _unauthorized(
            "Missing or invalid Authorization header. Expected: Bearer <api_key>"
        )
    if not compare_digest(token, current_key):
        return _unauthorized("Invalid API key")
    return None


def _ip_is_public(raw: str) -> bool:
    """True for globally routable IPs (not private/loopback/link-local/unspecified)."""
    try:
        addr = ip_address(raw.strip())
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _parse_forwarded_header(value: str) -> list[str]:
    """Extract for= IPs from an RFC 7239 Forwarded header."""
    found: list[str] = []
    for part in value.split(","):
        for field in part.split(";"):
            field = field.strip()
            if field.lower().startswith("for="):
                candidate = field[4:].strip().strip('"')
                # Strip IPv6 brackets / optional port: [2001:db8::1]:443
                if candidate.startswith("["):
                    end = candidate.find("]")
                    candidate = candidate[1:end] if end != -1 else candidate
                elif candidate.count(":") == 1:
                    candidate = candidate.split(":", 1)[0]
                if candidate:
                    found.append(candidate)
    return found


def _client_ip_candidates() -> list[str]:
    """Ordered IP candidates from proxy headers + direct peer."""
    candidates: list[str] = []

    for header in ("CF-Connecting-IP", "True-Client-IP", "X-Real-IP"):
        value = (request.headers.get(header) or "").strip()
        if value:
            candidates.append(value)

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        candidates.extend(part.strip() for part in forwarded.split(",") if part.strip())

    fwd = request.headers.get("Forwarded", "")
    if fwd:
        candidates.extend(_parse_forwarded_header(fwd))

    # Flask access_route = X-Forwarded-For hops + remote_addr
    try:
        candidates.extend(str(ip).strip() for ip in request.access_route if ip)
    except Exception:
        pass

    peer = (getattr(request, "environ", {}) or {}).get("REMOTE_ADDR") or request.remote_addr or ""
    peer = str(peer).strip()
    if peer:
        candidates.append(peer)

    # De-dupe, preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for ip in candidates:
        # Normalize IPv4-mapped IPv6
        if ip.lower().startswith("::ffff:"):
            ip = ip[7:]
        if not ip or ip in seen:
            continue
        seen.add(ip)
        ordered.append(ip)
    return ordered


def _client_ip() -> str:
    """
    Best-effort original client IP.
    Prefers the leftmost public IP from proxy headers (ALB/Traefik/Cloudflare),
    otherwise the first candidate (may be private when Docker NAT hides the peer).
    """
    candidates = _client_ip_candidates()
    for ip in candidates:
        if _ip_is_public(ip):
            return ip
    return candidates[0] if candidates else ""


def _peer_ip() -> str:
    """Immediate TCP peer (often the Docker bridge / proxy, not the internet client)."""
    peer = (request.remote_addr or "").strip()
    if peer.lower().startswith("::ffff:"):
        peer = peer[7:]
    return peer


def _is_localhost_request() -> bool:
    """True when the request originates from loopback / localhost."""
    raw = _client_ip()
    if not raw:
        return False
    if raw.lower() in {"localhost", "::ffff:127.0.0.1"}:
        return True
    # Strip IPv4-mapped IPv6 prefix if present
    if raw.lower().startswith("::ffff:"):
        raw = raw[7:]
    try:
        return ip_address(raw).is_loopback
    except ValueError:
        return raw in {"127.0.0.1", "::1"}


def _should_log_request() -> bool:
    path = request.path
    if not path.startswith("/api/"):
        return False
    if any(path.startswith(prefix) for prefix in SKIP_DEBUG_PREFIXES):
        return False
    if request.headers.get("X-TrafficLight-UI") == "1":
        return False
    # Only show external traffic in the live monitor
    if _is_localhost_request():
        return False
    return True


def _safe_headers() -> dict:
    headers = {}
    for key, value in request.headers.items():
        if key.lower() == "authorization":
            headers[key] = "Bearer ***" if value.lower().startswith("bearer ") else "***"
        else:
            headers[key] = value
    return headers


def _safe_body() -> str | None:
    raw = request.get_data(cache=True, as_text=True)
    if not raw:
        return None
    if len(raw) > MAX_BODY_CHARS:
        return raw[:MAX_BODY_CHARS] + f"\n… truncated ({len(raw)} chars total)"
    return raw


def _safe_response_body(response) -> str | None:
    if response.direct_passthrough:
        return None
    try:
        data = response.get_data(as_text=True)
    except Exception:
        return None
    if not data:
        return None
    if len(data) > MAX_BODY_CHARS:
        return data[:MAX_BODY_CHARS] + f"\n… truncated ({len(data)} chars total)"
    return data


@app.before_request
def _debug_before_request():
    if not _should_log_request():
        return
    g._debug_start = perf_counter()
    g._debug_entry = {
        "id": str(uuid4()),
        "method": request.method,
        "path": request.path,
        "query": request.query_string.decode("utf-8", errors="replace") or None,
        "remote_addr": _client_ip() or _peer_ip() or request.remote_addr,
        "client_ip": _client_ip() or None,
        "peer_addr": _peer_ip() or None,
        "forwarded_for": request.headers.get("X-Forwarded-For"),
        "headers": _safe_headers(),
        "body": _safe_body(),
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
    }


@app.before_request
def _auth_before_request():
    return _require_api_key()


@app.after_request
def _debug_after_request(response):
    entry = getattr(g, "_debug_entry", None)
    if entry is None:
        return response

    global request_seq
    started = getattr(g, "_debug_start", None)
    duration_ms = round((perf_counter() - started) * 1000, 2) if started else None

    entry.update({
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "response_headers": dict(response.headers),
        "response_body": _safe_response_body(response),
    })

    with request_log_lock:
        request_seq += 1
        entry["seq"] = request_seq
        request_log.appendleft(entry)

    return response


def _status_payload(*, success: bool = True, message: str | None = None, error: str | None = None) -> dict:
    """Public status view — persistent failure always reports color as 'failure'."""
    payload = {
        "color": traffic_light_state["color"],
        "persistent": bool(traffic_light_state.get("persistent")),
        "timestamp": traffic_light_state["timestamp"],
        "success": success,
    }
    if message is not None:
        payload["message"] = message
    if error is not None:
        payload["error"] = error
    return payload


@app.route('/')
def index():
    """Main page"""
    return render_template(
        'index.html',
        current_color=traffic_light_state["color"],
        persistent=bool(traffic_light_state.get("persistent")),
        api_key=_get_api_key(),
        serial_number=_get_serial_number(),
        default_serial_number=DEFAULT_SERIAL_NUMBER,
    )


@app.route('/api/settings/reset', methods=['POST'])
def reset_app_state():
    """Full in-memory state reset. Clears persistent failure, traffic log, and restores defaults."""
    global request_seq

    traffic_light_state["color"] = "red"
    traffic_light_state["persistent"] = False
    traffic_light_state["timestamp"] = datetime.now().isoformat()

    with request_log_lock:
        request_log.clear()
        request_seq = 0

    restored_key = _set_api_key(DEFAULT_API_KEY)
    restored_serial = _set_serial_number(DEFAULT_SERIAL_NUMBER)

    return jsonify({
        "success": True,
        "message": "Application state reset",
        "color": traffic_light_state["color"],
        "persistent": False,
        "api_key": restored_key,
        "auth_enabled": bool(restored_key),
        "serial_number": restored_serial,
        "timestamp": traffic_light_state["timestamp"],
    })


def _call_local_agent(message: str) -> tuple[bool, str, int | None]:
    """
    Send a user message to the local OpenAI-compatible agent gateway.
    Returns (ok, detail_or_reply, http_status).
    """
    try:
        client = OpenAI(base_url=_agent_base_url(), api_key=_agent_api_key())
        response = client.chat.completions.create(
            model=_agent_model(),
            messages=[{"role": "user", "content": message}],
            extra_body={"agent_id": _agent_id()},
        )
        content = ""
        if response.choices:
            content = (response.choices[0].message.content or "").strip()
        return True, content or "Agent responded with empty content", 200
    except APITimeoutError:
        return False, "Timed out waiting for local agent", None
    except APIConnectionError as exc:
        return False, f"Could not reach local agent at {_agent_base_url()}: {exc}", None
    except APIStatusError as exc:
        detail = ""
        try:
            detail = str(exc.response.json())
        except Exception:
            detail = (getattr(exc, "message", None) or str(exc))[:400]
        return False, f"Agent API error ({exc.status_code}): {detail}", exc.status_code
    except OpenAIError as exc:
        return False, f"Agent request failed: {exc}", None
    except Exception as exc:
        return False, f"Agent request failed: {exc}", None


@app.route('/api/settings/force-agent-check', methods=['POST'])
def force_agent_check():
    """Send 'Inspect the light' to the local agent and return its reply."""
    ok, detail, upstream_status = _call_local_agent(AGENT_FORCE_CHECK_MESSAGE)
    if ok:
        return jsonify({
            "success": True,
            "message": detail,
            "delivered": True,
            "upstream_status": upstream_status,
        })

    status_code = 502
    if upstream_status is None and "Could not reach" in detail:
        status_code = 503
    elif upstream_status is not None and upstream_status >= 400:
        status_code = 502
    return jsonify({
        "success": False,
        "error": detail,
        "delivered": False,
        "upstream_status": upstream_status,
    }), status_code


@app.route('/docs')
def docs():
    """API documentation page"""
    return render_template('docs.html', api_key=_get_api_key())


@app.route('/api/settings/api-key', methods=['GET'])
def get_api_key_setting():
    """Return the current API key"""
    current = _get_api_key()
    return jsonify({
        "success": True,
        "api_key": current,
        "auth_enabled": bool(current),
    })


@app.route('/api/settings/api-key', methods=['PUT'])
def update_api_key_setting():
    """Set the API key used for Bearer auth"""
    data = request.get_json(silent=True) or {}
    if "api_key" not in data:
        return jsonify({
            "success": False,
            "error": "Missing 'api_key' field in request body",
        }), 400

    new_key = data["api_key"]
    if new_key is None:
        new_key = ""
    if not isinstance(new_key, str):
        return jsonify({
            "success": False,
            "error": "'api_key' must be a string (use empty string to disable auth)",
        }), 400

    saved = _set_api_key(new_key.strip())
    return jsonify({
        "success": True,
        "api_key": saved,
        "auth_enabled": bool(saved),
        "message": (
            "API key updated — Bearer auth enabled"
            if saved
            else "API key cleared — Bearer auth disabled"
        ),
    })


@app.route('/api/settings/serial-number', methods=['GET'])
def get_serial_number_setting():
    """Return the current traffic-light serial number"""
    current = _get_serial_number()
    return jsonify({
        "success": True,
        "serial_number": current,
        "location_id": current,
    })


@app.route('/api/settings/serial-number', methods=['PUT'])
def update_serial_number_setting():
    """Set the traffic-light serial / location ID (exactly 10 digits)"""
    data = request.get_json(silent=True) or {}
    serial, error = _normalize_serial_number(data.get("serial_number"))
    if error:
        return jsonify({"success": False, "error": error}), 400

    saved = _set_serial_number(serial)
    return jsonify({
        "success": True,
        "serial_number": saved,
        "location_id": saved,
        "message": f"Serial number updated to {saved}",
    })


@app.route('/api/debug/requests', methods=['GET'])
def get_debug_requests():
    """Return recent API requests for the live traffic monitor"""
    since = request.args.get("since", type=int, default=0)
    with request_log_lock:
        entries = [e for e in request_log if e["seq"] > since]
        latest_seq = request_seq
    return jsonify({
        "success": True,
        "latest_seq": latest_seq,
        "count": len(entries),
        "requests": entries,
    })


@app.route('/api/debug/requests', methods=['DELETE'])
def clear_debug_requests():
    """Clear the in-memory API request log"""
    global request_seq
    with request_log_lock:
        request_log.clear()
        request_seq = 0
    return jsonify({"success": True, "message": "Request log cleared"})


@app.route('/api/traffic-light/status', methods=['GET'])
def get_traffic_light_status():
    """Get the current traffic light status"""
    return jsonify(_status_payload())


@app.route('/api/traffic-light/status', methods=['POST'])
def set_traffic_light_status():
    """Set the traffic light color / failure mode"""
    try:
        data = request.get_json()

        if not data or 'color' not in data:
            return jsonify({
                "success": False,
                "error": "Missing 'color' field in request body",
                "color": traffic_light_state["color"],
                "persistent": bool(traffic_light_state.get("persistent")),
            }), 400

        requested = str(data['color']).lower().strip()

        # Persistent failure: no color/mode change is ever allowed
        if traffic_light_state.get("persistent"):
            return jsonify(_status_payload(
                success=False,
                error=(
                    "Traffic light is in persistent failure mode. "
                    "Setting another color is not possible."
                ),
            )), 409

        if requested not in VALID_SET_COLORS:
            return jsonify({
                "success": False,
                "error": f"Invalid color. Must be one of: {', '.join(VALID_SET_COLORS)}",
                "color": traffic_light_state["color"],
                "persistent": bool(traffic_light_state.get("persistent")),
            }), 400

        if requested == "persistent_failure":
            traffic_light_state["color"] = "failure"
            traffic_light_state["persistent"] = True
            message = (
                "Traffic light set to persistent failure mode (amber blinking) — "
                "color changes are permanently blocked"
            )
        elif requested == "failure":
            traffic_light_state["color"] = "failure"
            traffic_light_state["persistent"] = False
            message = "Traffic light set to recoverable failure mode (amber blinking)"
        else:
            traffic_light_state["color"] = requested
            traffic_light_state["persistent"] = False
            message = f"Traffic light set to {requested}"

        traffic_light_state["timestamp"] = datetime.now().isoformat()
        return jsonify(_status_payload(message=message))

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/traffic-light/colors', methods=['GET'])
def get_valid_colors():
    """Get list of normal settable colors (failure modes are omitted on purpose)"""
    return jsonify({
        "colors": LISTED_COLORS,
        "success": True
    })


@app.route('/api/traffic-light/location-id', methods=['GET'])
def get_location_id():
    """Get the traffic light location ID (serial number)"""
    serial = _get_serial_number()
    return jsonify({
        "location_id": serial,
        "serial_number": serial,
        "success": True,
    })


@app.route('/api/registry/traffic-lights', methods=['GET'])
def registry_list_traffic_lights():
    """List traffic lights from the inventory database (paginated, or all=true for full dump)."""
    all_rows = str(request.args.get("all", "")).strip().lower() in {"1", "true", "yes"}
    limit = 50
    offset = 0
    if not all_rows:
        try:
            limit = int(request.args.get("limit", 50))
            offset = int(request.args.get("offset", 0))
        except ValueError:
            return jsonify({"success": False, "error": "limit/offset must be integers"}), 400

    items, total = traffic_lights_db.list_traffic_lights(
        city=request.args.get("city"),
        q=request.args.get("q"),
        limit=limit,
        offset=offset,
        all_rows=all_rows,
    )
    payload = {
        "success": True,
        "total": total,
        "count": len(items),
        "traffic_lights": items,
    }
    if all_rows:
        payload["all"] = True
    else:
        payload["limit"] = max(1, min(limit, 10_000))
        payload["offset"] = max(0, offset)
    return jsonify(payload)


@app.route('/api/registry/traffic-lights/<serial_number>', methods=['GET'])
def registry_get_traffic_light(serial_number: str):
    """Get one traffic light by serial number."""
    item = traffic_lights_db.get_traffic_light(serial_number)
    if item is None:
        return jsonify({"success": False, "error": "Traffic light not found"}), 404
    return jsonify({"success": True, "traffic_light": item})


@app.route('/api/registry/traffic-lights', methods=['POST'])
def registry_create_traffic_light():
    """Create a traffic light inventory record."""
    payload, error = traffic_lights_db.validate_traffic_light_payload(
        request.get_json(silent=True),
        partial=False,
    )
    if error:
        return jsonify({"success": False, "error": error}), 400
    try:
        item = traffic_lights_db.create_traffic_light(payload)
    except IntegrityError:
        return jsonify({
            "success": False,
            "error": f"Serial number {payload['serial_number']} already exists",
        }), 409
    return jsonify({
        "success": True,
        "message": "Traffic light created",
        "traffic_light": item,
    }), 201


@app.route('/api/registry/traffic-lights/<serial_number>', methods=['PUT'])
def registry_update_traffic_light(serial_number: str):
    """Update a traffic light inventory record (partial updates allowed)."""
    data = request.get_json(silent=True) or {}
    if "serial_number" in data and str(data["serial_number"]).strip() != serial_number:
        return jsonify({
            "success": False,
            "error": "serial_number in body must match URL (or be omitted)",
        }), 400
    payload, error = traffic_lights_db.validate_traffic_light_payload(data, partial=True)
    if error:
        return jsonify({"success": False, "error": error}), 400
    if not payload:
        return jsonify({"success": False, "error": "No updatable fields provided"}), 400
    payload.pop("serial_number", None)
    item = traffic_lights_db.update_traffic_light(serial_number, payload)
    if item is None:
        return jsonify({"success": False, "error": "Traffic light not found"}), 404
    return jsonify({
        "success": True,
        "message": "Traffic light updated",
        "traffic_light": item,
    })


@app.route('/api/registry/traffic-lights/<serial_number>', methods=['DELETE'])
def registry_delete_traffic_light(serial_number: str):
    """Delete a traffic light inventory record."""
    deleted = traffic_lights_db.delete_traffic_light(serial_number)
    if not deleted:
        return jsonify({"success": False, "error": "Traffic light not found"}), 404
    return jsonify({
        "success": True,
        "message": f"Traffic light {serial_number} deleted",
    })


if __name__ == '__main__':
    # Production WSGI locally and in Docker (config matches Dockerfile)
    from gunicorn.app.wsgiapp import run as gunicorn_run
    import sys

    sys.argv = ["gunicorn", "--config", "gunicorn_conf.py", "app:app"]
    gunicorn_run()
