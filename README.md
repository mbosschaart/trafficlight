# Traffic Light Control System

Demo Flask app for controlling a virtual traffic light, inspecting live API traffic, looking up a seeded Dutch inventory database, and triggering a local OpenAI-compatible agent.

**Default URLs (Docker)**

| Surface | URL |
|---------|-----|
| Web UI | http://localhost:5005 |
| API docs | http://localhost:5005/docs |
| Control API | http://localhost:5005/api/traffic-light/* |
| Inventory registry | http://localhost:5005/api/registry/traffic-lights |

Host port **5005** maps to container port **8065**.

---

## Features

- Interactive traffic light UI (red / amber / green + failure modes)
- REST control API with Bearer auth
- Mutable API key and serial/location ID from the UI
- Live request monitor for inbound API calls
- SQLite registry of **1000** fake Dutch traffic lights with full CRUD
- Force Agent Check via a local OpenAI-compatible gateway
- Built-in HTML API documentation at `/docs`

---

## Architecture

```
┌─────────────────┐     Bearer      ┌──────────────────────────────┐
│  Web UI / Agent │ ──────────────► │  Flask + Gunicorn (:8065)    │
└─────────────────┘                 │  - in-memory light state     │
                                    │  - SQLite registry (1000)    │
                                    │  - settings / debug APIs     │
                                    └──────────────┬───────────────┘
                                                   │ Force Agent Check
                                                   ▼
                                    ┌──────────────────────────────┐
                                    │ Local agent gateway (:5050)  │
                                    │ OpenAI-compatible /v1        │
                                    └──────────────────────────────┘
```

| Component | Role |
|-----------|------|
| `app.py` | Flask routes, auth, light state, agent client, debug log |
| `db.py` | SQLite registry helpers + seed loading |
| `data/traffic_lights_seed.json` | Seed data for 1000 inventory records |
| `templates/index.html` | Main control UI |
| `templates/docs.html` | In-browser API reference |
| `gunicorn_conf.py` | Production WSGI config (1 worker, quiet UI logs) |

**State that survives restart**

- Registry DB (Docker volume `traffic-lights-db` → `/app/var/traffic_lights.db`)

**State that resets on process restart**

- Current light color / persistent failure flag
- Runtime API key (unless set again via env / UI)
- Runtime serial number (unless set again via env / UI)
- In-memory API traffic log

---

## Quick start

### Docker Compose (recommended)

```bash
docker compose up -d --build
```

Then open http://localhost:5005

```bash
docker compose logs -f          # logs
docker compose restart          # restart
docker compose down             # stop
```

### deploy.sh

```bash
./deploy.sh start|stop|restart|status|logs|clean
```

### Local Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Gunicorn binds to `PORT` (default **8065**). For local access on 5005:

```bash
PORT=5005 python app.py
```

---

## Authentication

When an API key is set (default: `secretapikey`), these paths require:

```http
Authorization: Bearer <api_key>
```

- `/api/traffic-light/*`
- `/api/registry/*`

Empty API key disables auth. Change the key on the main UI or via `API_KEY` / `/api/settings/api-key`.

UI and settings/debug routes do **not** require Bearer auth.

---

## Traffic light control

### Colors

| Value | Listed by `GET /colors` | Meaning |
|-------|-------------------------|---------|
| `red` | yes | Solid red |
| `amber` | yes | Solid amber |
| `green` | yes | Solid green |
| `failure` | no | Recoverable failure (blinking amber) |
| `persistent_failure` | no | Persistent failure; blocks further color changes until reset |

`GET /api/traffic-light/status` always reports failure modes as `"color": "failure"`. Persistent mode is indicated by `"persistent": true`.

### Endpoints

#### `GET /api/traffic-light/status`

```json
{
  "color": "red",
  "persistent": false,
  "timestamp": "2026-09-12T12:00:00.000000",
  "success": true
}
```

#### `POST /api/traffic-light/status`

```json
{ "color": "green" }
```

Accepted colors: `red`, `amber`, `green`, `failure`, `persistent_failure`.

Returns **409** if the light is in persistent failure and another color is requested.

#### `GET /api/traffic-light/colors`

```json
{
  "colors": ["red", "amber", "green"],
  "success": true
}
```

#### `GET /api/traffic-light/location-id`

Returns the active 10-digit serial / location ID (default `4829173056`).

```json
{
  "location_id": "4829173056",
  "serial_number": "4829173056",
  "success": true
}
```

Changeable from the UI or `PUT /api/settings/serial-number`.

### curl examples

```bash
export API_KEY=secretapikey
export BASE=http://localhost:5005

curl -s -H "Authorization: Bearer $API_KEY" "$BASE/api/traffic-light/status"

curl -s -X POST -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"color":"amber"}' "$BASE/api/traffic-light/status"

curl -s -H "Authorization: Bearer $API_KEY" "$BASE/api/traffic-light/colors"

curl -s -H "Authorization: Bearer $API_KEY" "$BASE/api/traffic-light/location-id"
```

---

## Inventory registry (SQLite)

Seeded with **1000** traffic lights across Dutch cities. Each record:

| Field | Description |
|-------|-------------|
| `serial_number` | Unique 10-digit ID |
| `city` | Dutch city name |
| `address` | Street address |
| `latitude` / `longitude` | GPS near the street corridor |
| `operational_since` | ISO date (`YYYY-MM-DD`) |
| `created_at` / `updated_at` | UTC timestamps |

**Special record:** serial `4829173056` → **Vredenburg 40, Utrecht**.

Seed source: `data/traffic_lights_seed.json`  
Runtime DB: `var/traffic_lights.db` (or `TRAFFIC_LIGHTS_DB`)

### CRUD endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/registry/traffic-lights` | List (paginated) |
| `GET` | `/api/registry/traffic-lights?all=true` | **Full database in one call** |
| `GET` | `/api/registry/traffic-lights/<serial>` | Get one |
| `POST` | `/api/registry/traffic-lights` | Create |
| `PUT` | `/api/registry/traffic-lights/<serial>` | Update (partial OK) |
| `DELETE` | `/api/registry/traffic-lights/<serial>` | Delete |

**List query params**

| Param | Description |
|-------|-------------|
| `limit` | Page size (default 50, max 10000) |
| `offset` | Skip N rows |
| `city` | Exact city filter |
| `q` | Search serial / address / city |
| `all` | `true` / `1` / `yes` → return every matching row |

**Create body**

```json
{
  "serial_number": "9999999999",
  "city": "Utrecht",
  "address": "Domplein 1, 3512 JC Utrecht",
  "latitude": 52.0907,
  "longitude": 5.1214,
  "operational_since": "2018-03-12"
}
```

```bash
# Entire registry
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE/api/registry/traffic-lights?all=true" | jq '.total'

# Default Utrecht light
curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE/api/registry/traffic-lights/4829173056"
```

An export snapshot may also exist at `data/traffic_lights_export.json`.

---

## Settings & UI helpers

These endpoints power the web UI (no Bearer required).

| Method | Path | Description |
|--------|------|-------------|
| `GET` / `PUT` | `/api/settings/api-key` | Read / set Bearer API key (`""` disables auth) |
| `GET` / `PUT` | `/api/settings/serial-number` | Read / set 10-digit serial |
| `POST` | `/api/settings/reset` | Reset light to red, clear traffic log, restore default API key + serial |
| `POST` | `/api/settings/force-agent-check` | Send `"Inspect the light"` to the local agent |
| `GET` | `/api/debug/requests?since=<seq>` | Recent API request log |
| `DELETE` | `/api/debug/requests` | Clear request log |

### Force Agent Check

Uses the OpenAI Python client against a local gateway:

| Env var | Default |
|---------|---------|
| `AGENT_BASE_URL` | `http://127.0.0.1:5050/v1` (Compose uses `host.docker.internal`) |
| `AGENT_API_KEY` | `agent-local-key` |
| `AGENT_ID` | `default` |
| `AGENT_MODEL` | `default` |

Message sent: **`Inspect the light`**. The agent reply is returned in the JSON `message` field.

The agent gateway must be reachable from the container (host port **5050** when using Docker Desktop).

---

## Web UI

http://localhost:5005

- Traffic light visualization + color / failure controls
- Force Agent Check, Reset State
- API key editor
- Serial / location ID editor (prefilled with default `4829173056`)
- Live API traffic monitor (method/path filters, pause, clear)
- Link to `/docs`

---

## Configuration

Loaded from environment / `.env` (missing keys only; existing env wins).

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8065` | Listen port inside process/container |
| `API_KEY` | `secretapikey` | Initial Bearer key |
| `SERIAL_NUMBER` | `4829173056` | Initial location serial (10 digits) |
| `AGENT_BASE_URL` | `http://127.0.0.1:5050/v1` | Agent OpenAI base URL |
| `AGENT_API_KEY` | `agent-local-key` | Agent API key |
| `AGENT_ID` | `default` | `extra_body.agent_id` |
| `AGENT_MODEL` | `default` | Chat model name |
| `TRAFFIC_LIGHTS_DB` | `var/traffic_lights.db` | SQLite path |
| `FLASK_ENV` | `production` (Compose) | Flask env flag |

Example `.env`:

```env
AGENT_BASE_URL=http://host.docker.internal:5050/v1
AGENT_API_KEY=agent-local-key
AGENT_ID=default
AGENT_MODEL=default
```

---

## HTTP status codes

| Code | Typical meaning |
|------|-----------------|
| 200 | Success |
| 201 | Registry record created |
| 400 | Validation error |
| 401 | Missing/invalid Bearer token |
| 409 | Duplicate serial, or color change blocked by persistent failure |
| 404 | Registry record not found |
| 502 / 503 | Agent unreachable or upstream error |
| 500 | Unexpected server error |

---

## Project layout

```
app.py                 # Flask application
db.py                  # SQLite registry
gunicorn_conf.py       # Gunicorn config
requirements.txt
Dockerfile
docker-compose.yml
deploy.sh
data/
  traffic_lights_seed.json     # 1000-record seed
  traffic_lights_export.json   # optional JSON export
templates/
  index.html
  docs.html
var/                   # local SQLite (gitignored)
```

---

## Technology stack

- Python 3.11, Flask, Gunicorn
- SQLite (stdlib)
- OpenAI Python SDK (local agent client)
- Tailwind CSS (CDN) + vanilla JS UI
- Docker / Docker Compose

---

## Exposing publicly (optional)

```bash
ngrok http 5005
```

Use the generated HTTPS URL as the base for external agents or demos. The free ngrok URL is public — treat the API key accordingly.

---

## License

MIT
