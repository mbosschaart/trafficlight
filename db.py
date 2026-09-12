"""SQLite registry of traffic lights (inventory / asset database)."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("TRAFFIC_LIGHTS_DB", str(BASE_DIR / "var" / "traffic_lights.db")))
SEED_PATH = BASE_DIR / "data" / "traffic_lights_seed.json"

_db_lock = Lock()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(*, force_reseed: bool = False) -> None:
    """Create schema and seed 1000 lights if the table is empty."""
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traffic_lights (
                    serial_number TEXT PRIMARY KEY,
                    city TEXT NOT NULL,
                    address TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    operational_since TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_traffic_lights_city ON traffic_lights(city)"
            )
            count = conn.execute("SELECT COUNT(*) FROM traffic_lights").fetchone()[0]
            if force_reseed:
                conn.execute("DELETE FROM traffic_lights")
                count = 0
            if count == 0:
                _seed(conn)
            conn.commit()
        finally:
            conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    if not SEED_PATH.is_file():
        raise FileNotFoundError(f"Seed file missing: {SEED_PATH}")
    records = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    now = _utcnow_iso()
    rows = [
        (
            r["serial_number"],
            r["city"],
            r["address"],
            float(r["latitude"]),
            float(r["longitude"]),
            r["operational_since"],
            now,
            now,
        )
        for r in records
    ]
    conn.executemany(
        """
        INSERT INTO traffic_lights (
            serial_number, city, address, latitude, longitude,
            operational_since, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "serial_number": row["serial_number"],
        "city": row["city"],
        "address": row["address"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "operational_since": row["operational_since"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_traffic_lights(
    *,
    city: str | None = None,
    q: str | None = None,
    limit: int | None = 50,
    offset: int = 0,
    all_rows: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    offset = max(0, int(offset))
    if all_rows:
        limit_sql: int | None = None
    else:
        limit_sql = max(1, min(int(limit if limit is not None else 50), 10_000))
    clauses: list[str] = []
    params: list[Any] = []
    if city:
        clauses.append("city = ?")
        params.append(city.strip())
    if q:
        clauses.append("(serial_number LIKE ? OR address LIKE ? OR city LIKE ?)")
        like = f"%{q.strip()}%"
        params.extend([like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _db_lock:
        conn = _connect()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM traffic_lights {where}", params
            ).fetchone()[0]
            sql = f"""
                SELECT * FROM traffic_lights
                {where}
                ORDER BY city ASC, serial_number ASC
            """
            query_params = list(params)
            if limit_sql is not None:
                sql += " LIMIT ? OFFSET ?"
                query_params.extend([limit_sql, offset])
            rows = conn.execute(sql, query_params).fetchall()
            return [_row_to_dict(r) for r in rows], int(total)
        finally:
            conn.close()


def get_traffic_light(serial_number: str) -> dict[str, Any] | None:
    with _db_lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM traffic_lights WHERE serial_number = ?",
                (serial_number,),
            ).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()


def create_traffic_light(payload: dict[str, Any]) -> dict[str, Any]:
    now = _utcnow_iso()
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO traffic_lights (
                    serial_number, city, address, latitude, longitude,
                    operational_since, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["serial_number"],
                    payload["city"],
                    payload["address"],
                    payload["latitude"],
                    payload["longitude"],
                    payload["operational_since"],
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM traffic_lights WHERE serial_number = ?",
                (payload["serial_number"],),
            ).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()


def update_traffic_light(serial_number: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    existing = get_traffic_light(serial_number)
    if existing is None:
        return None
    merged = {**existing, **payload, "serial_number": serial_number}
    now = _utcnow_iso()
    with _db_lock:
        conn = _connect()
        try:
            conn.execute(
                """
                UPDATE traffic_lights
                SET city = ?, address = ?, latitude = ?, longitude = ?,
                    operational_since = ?, updated_at = ?
                WHERE serial_number = ?
                """,
                (
                    merged["city"],
                    merged["address"],
                    merged["latitude"],
                    merged["longitude"],
                    merged["operational_since"],
                    now,
                    serial_number,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM traffic_lights WHERE serial_number = ?",
                (serial_number,),
            ).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()


def delete_traffic_light(serial_number: str) -> bool:
    with _db_lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM traffic_lights WHERE serial_number = ?",
                (serial_number,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def validate_traffic_light_payload(
    data: dict[str, Any] | None,
    *,
    partial: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(data, dict):
        return None, "JSON body required"

    required = ("serial_number", "city", "address", "latitude", "longitude", "operational_since")
    out: dict[str, Any] = {}

    if not partial:
        missing = [f for f in required if f not in data]
        if missing:
            return None, f"Missing fields: {', '.join(missing)}"

    if "serial_number" in data or not partial:
        serial = data.get("serial_number")
        if not isinstance(serial, str) or not serial.strip().isdigit() or len(serial.strip()) != 10:
            return None, "'serial_number' must be exactly 10 digits"
        out["serial_number"] = serial.strip()

    if "city" in data or not partial:
        city = data.get("city")
        if not isinstance(city, str) or not city.strip():
            return None, "'city' must be a non-empty string"
        out["city"] = city.strip()

    if "address" in data or not partial:
        address = data.get("address")
        if not isinstance(address, str) or not address.strip():
            return None, "'address' must be a non-empty string"
        out["address"] = address.strip()

    for field in ("latitude", "longitude"):
        if field in data or not partial:
            raw = data.get(field)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return None, f"'{field}' must be a number"
            if field == "latitude" and not (-90.0 <= value <= 90.0):
                return None, "'latitude' must be between -90 and 90"
            if field == "longitude" and not (-180.0 <= value <= 180.0):
                return None, "'longitude' must be between -180 and 180"
            out[field] = value

    if "operational_since" in data or not partial:
        op = data.get("operational_since")
        if not isinstance(op, str):
            return None, "'operational_since' must be an ISO date (YYYY-MM-DD)"
        try:
            date.fromisoformat(op.strip())
        except ValueError:
            return None, "'operational_since' must be an ISO date (YYYY-MM-DD)"
        out["operational_since"] = op.strip()

    return out, None
