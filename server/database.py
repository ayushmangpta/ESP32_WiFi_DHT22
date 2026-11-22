"""
Database module for ESP32 DHT22 Sensor Logger & Automation.

Uses aiosqlite for async SQLite operations.
The database file (sensor_data.db) is created automatically
in the server/ directory.

Tables:
  - 'readings': ESP32 DHT22 sensor readings
  - 'smart_plug_state': Current verified / last known state of each plug
  - 'smart_plug_history': Audit log of all manual and automated plug commands
  - 'automation_settings': Persistent key-value automation thresholds & schedule config
  - 'automation_rules': Persistent relational condition rules for environmental control
"""

import aiosqlite
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

# Database file path — same directory as this script
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensor_data.db")

# In-memory settings cache for instant synchronous access
_SETTINGS_CACHE: Dict[str, Any] = {}

# ─── Default Automation Definitions for SQL Seeding ────────────

DEFAULT_SETTINGS_DEFINITIONS = [
    ("enabled", "true", "bool", "Master toggle for automated smart plug actions"),
    ("window_size", "30", "int", "Number of recent valid sensor readings for moving average"),
    ("humidifier_humid_low", "93.0", "float", "Turn ON humidifier when average humidity drops below this %"),
    ("humidifier_humid_high", "96.0", "float", "Turn OFF humidifier when average humidity exceeds this %"),
    ("ac_temp_high", "26.0", "float", "Turn ON AC when average temperature exceeds this °C"),
    ("ac_temp_low", "23.0", "float", "Turn OFF AC when average temperature drops below this °C"),
    ("heater_temp_low", "22.0", "float", "Turn ON Space Heater when average temperature drops below this °C"),
    ("heater_temp_high", "26.0", "float", "Target temperature for Space Heater (turns OFF at or above this °C)"),
    ("fan_humid_trigger_threshold", "96.0", "float", "Trigger Fan ON when average humidity exceeds this %"),
    ("fan_humidity_trigger_duration_mins", "3.0", "float", "Duration (mins) to run Fan when triggered by high humidity"),
    ("fan_schedule_interval_hours", "4.0", "float", "Interval (hours) between periodic Fan ventilation cycles"),
    ("fan_schedule_duration_mins", "5.0", "float", "Duration (mins) of periodic Fan ventilation cycles"),
    ("sprinkler_schedule_interval_hours", "2.0", "float", "Interval (hours) between periodic Sprinkler irrigation cycles"),
    ("sprinkler_schedule_duration_mins", "5.0", "float", "Duration (mins) of periodic Sprinkler irrigation cycles"),
]

DEFAULT_RULES_DEFINITIONS = [
    ("humidifier_low", "humidifier", "threshold", "humidity", "<", 93.0, None, None, None, "If humidity < 93%, turn ON humidifier"),
    ("humidifier_high", "humidifier", "threshold", "humidity", ">", 96.0, None, None, None, "If humidity > 96%, turn OFF humidifier"),
    ("sprinkler_scheduled", "sprinkler", "schedule", "time", "interval", None, None, 5.0, 2.0, "Water sprinkler scheduled for 5 mins once every 2 hours"),
    ("ac_high", "ac", "threshold", "temperature", ">", 26.0, None, None, None, "If temperature > 26°C, turn ON AC"),
    ("ac_low", "ac", "threshold", "temperature", "<", 23.0, None, None, None, "If temperature < 23°C, turn OFF AC"),
    ("heater_cold", "heater", "threshold", "temperature", "<", 22.0, 26.0, None, None, "If temperature < 22°C, turn ON heater until temp 26°C"),
    ("fan_humidity", "fan", "threshold", "humidity", ">", 96.0, None, 3.0, None, "If humidity > 96%, turn ON fan for 3 mins"),
    ("fan_scheduled", "fan", "schedule", "time", "interval", None, None, 5.0, 4.0, "Turn ON fan every 4 hours for 5 mins"),
]


def _parse_setting_value(val: str, vtype: str) -> Any:
    """Cast database string representation to its Python data type."""
    if vtype == "bool":
        return val.lower() in ("true", "1", "yes")
    elif vtype == "int":
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return 0
    elif vtype == "float":
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
    return val


async def init_db():
    """
    Create database tables if they do not exist:
    - 'readings': ESP32 DHT22 sensor readings
    - 'smart_plug_state': Current verified / last known state of each plug
    - 'smart_plug_history': Audit log of all manual and automated plug commands
    - 'automation_settings': Persistent SQL table of automation thresholds and schedules
    - 'automation_rules': Persistent SQL table of condition definitions
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Sensor readings table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                temperature REAL    NOT NULL,
                humidity    REAL    NOT NULL,
                timestamp   TEXT    NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_timestamp 
            ON readings (timestamp DESC)
        """)

        # 2. Smart plug current state table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS smart_plug_state (
                plug_name              TEXT PRIMARY KEY,
                current_state          TEXT NOT NULL DEFAULT 'UNKNOWN',
                is_verified            INTEGER NOT NULL DEFAULT 0,
                last_successful_check  TEXT,
                last_attempted_action  TEXT,
                last_action_result     TEXT,
                updated_at             TEXT NOT NULL
            )
        """)

        # 3. Smart plug event history table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS smart_plug_history (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                plug_name              TEXT NOT NULL,
                plug_ip                TEXT,
                requested_action       TEXT NOT NULL,
                previous_state         TEXT,
                resulting_state        TEXT,
                success                INTEGER NOT NULL,
                trigger_source         TEXT NOT NULL,
                temperature            REAL,
                humidity               REAL,
                sensor_readings_count  INTEGER,
                reason                 TEXT,
                error_message          TEXT,
                created_at             TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_plug_history_created 
            ON smart_plug_history (created_at DESC)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_plug_history_name 
            ON smart_plug_history (plug_name, created_at DESC)
        """)

        # 4. Automation settings SQL table (thresholds & config)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS automation_settings (
                key          TEXT PRIMARY KEY,
                value        TEXT NOT NULL,
                value_type   TEXT NOT NULL DEFAULT 'float',
                description  TEXT,
                updated_at   TEXT NOT NULL
            )
        """)

        # 5. Automation rules SQL table (relational condition definitions)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS automation_rules (
                rule_id        TEXT PRIMARY KEY,
                device_name    TEXT NOT NULL,
                rule_type      TEXT NOT NULL,
                trigger_metric TEXT,
                operator       TEXT,
                threshold      REAL,
                target_value   REAL,
                duration_mins  REAL,
                interval_hours REAL,
                description    TEXT,
                enabled        INTEGER NOT NULL DEFAULT 1,
                updated_at     TEXT NOT NULL
            )
        """)

        # Seed default settings into SQL table if not present (preserves user edits)
        now_iso = datetime.now().isoformat()
        for key, val, vtype, desc in DEFAULT_SETTINGS_DEFINITIONS:
            await db.execute("""
                INSERT OR IGNORE INTO automation_settings (key, value, value_type, description, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (key, val, vtype, desc, now_iso))

        # Seed default rules into SQL table if not present
        for rid, dname, rtype, metric, op, th, target, dur, interval, desc in DEFAULT_RULES_DEFINITIONS:
            await db.execute("""
                INSERT OR IGNORE INTO automation_rules (
                    rule_id, device_name, rule_type, trigger_metric, operator,
                    threshold, target_value, duration_mins, interval_hours, description, enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (rid, dname, rtype, metric, op, th, target, dur, interval, desc, now_iso))

        await db.commit()

    # Preload settings into cache
    await get_db_automation_settings()
    print(f"✓ Database ready at: {DB_PATH}")
    print(f"✓ Automation rules & settings loaded from SQL table: {len(_SETTINGS_CACHE)} parameters active")


# ─── Automation Settings SQL Operations ───────────────────────

async def get_db_automation_settings() -> Dict[str, Any]:
    """Retrieve all automation thresholds and parameters from the SQLite database."""
    global _SETTINGS_CACHE
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT key, value, value_type FROM automation_settings") as cursor:
            rows = await cursor.fetchall()
            settings = {}
            for row in rows:
                settings[row["key"]] = _parse_setting_value(row["value"], row["value_type"])
            _SETTINGS_CACHE = settings
            return dict(_SETTINGS_CACHE)


def get_cached_automation_settings() -> Dict[str, Any]:
    """Synchronous getter for automation settings from memory cache or sqlite3 fallback."""
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE:
        return dict(_SETTINGS_CACHE)

    # Fallback to direct synchronous sqlite3 query if called before async init_db
    try:
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT key, value, value_type FROM automation_settings")
            rows = cursor.fetchall()
            conn.close()
            settings = {}
            for row in rows:
                settings[row["key"]] = _parse_setting_value(row["value"], row["value_type"])
            if settings:
                _SETTINGS_CACHE = settings
                return dict(_SETTINGS_CACHE)
    except Exception as e:
        print(f"[database] Fallback sqlite3 query warning: {e}")

    # Fallback to defaults if DB is completely uninitialized
    fallback = {}
    for key, val, vtype, _ in DEFAULT_SETTINGS_DEFINITIONS:
        fallback[key] = _parse_setting_value(val, vtype)
    return fallback


async def update_db_automation_settings(updates: dict) -> Dict[str, Any]:
    """
    Update automation settings in the SQLite database table.
    Also synchronizes corresponding rows in the automation_rules table.
    """
    global _SETTINGS_CACHE
    now_iso = datetime.now().isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        for key, val in updates.items():
            if val is None:
                continue

            str_val = str(val).lower() if isinstance(val, bool) else str(val)

            # 1. Update key in automation_settings SQL table
            await db.execute("""
                UPDATE automation_settings
                SET value = ?, updated_at = ?
                WHERE key = ?
            """, (str_val, now_iso, key))

            # 2. Keep automation_rules table in sync
            if key == "humidifier_humid_low":
                await db.execute("UPDATE automation_rules SET threshold = ?, updated_at = ? WHERE rule_id = 'humidifier_low'", (float(val), now_iso))
            elif key == "humidifier_humid_high":
                await db.execute("UPDATE automation_rules SET threshold = ?, updated_at = ? WHERE rule_id = 'humidifier_high'", (float(val), now_iso))
            elif key == "ac_temp_high":
                await db.execute("UPDATE automation_rules SET threshold = ?, updated_at = ? WHERE rule_id = 'ac_high'", (float(val), now_iso))
            elif key == "ac_temp_low":
                await db.execute("UPDATE automation_rules SET threshold = ?, updated_at = ? WHERE rule_id = 'ac_low'", (float(val), now_iso))
            elif key == "heater_temp_low":
                await db.execute("UPDATE automation_rules SET threshold = ?, updated_at = ? WHERE rule_id = 'heater_cold'", (float(val), now_iso))
            elif key == "heater_temp_high":
                await db.execute("UPDATE automation_rules SET target_value = ?, updated_at = ? WHERE rule_id = 'heater_cold'", (float(val), now_iso))
            elif key == "fan_humid_trigger_threshold":
                await db.execute("UPDATE automation_rules SET threshold = ?, updated_at = ? WHERE rule_id = 'fan_humidity'", (float(val), now_iso))
            elif key == "fan_humidity_trigger_duration_mins":
                await db.execute("UPDATE automation_rules SET duration_mins = ?, updated_at = ? WHERE rule_id = 'fan_humidity'", (float(val), now_iso))
            elif key == "fan_schedule_interval_hours":
                await db.execute("UPDATE automation_rules SET interval_hours = ?, updated_at = ? WHERE rule_id = 'fan_scheduled'", (float(val), now_iso))
            elif key == "fan_schedule_duration_mins":
                await db.execute("UPDATE automation_rules SET duration_mins = ?, updated_at = ? WHERE rule_id = 'fan_scheduled'", (float(val), now_iso))
            elif key == "sprinkler_schedule_interval_hours":
                await db.execute("UPDATE automation_rules SET interval_hours = ?, updated_at = ? WHERE rule_id = 'sprinkler_scheduled'", (float(val), now_iso))
            elif key == "sprinkler_schedule_duration_mins":
                await db.execute("UPDATE automation_rules SET duration_mins = ?, updated_at = ? WHERE rule_id = 'sprinkler_scheduled'", (float(val), now_iso))
            elif key == "enabled":
                en_int = 1 if bool(val) else 0
                await db.execute("UPDATE automation_rules SET enabled = ?, updated_at = ?", (en_int, now_iso))

        await db.commit()

    # Reload into cache
    return await get_db_automation_settings()


async def get_db_automation_rules() -> List[Dict[str, Any]]:
    """Retrieve all structured automation rules from the SQLite database."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM automation_rules ORDER BY rule_id ASC") as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "rule_id": r["rule_id"],
                    "device_name": r["device_name"],
                    "rule_type": r["rule_type"],
                    "trigger_metric": r["trigger_metric"],
                    "operator": r["operator"],
                    "threshold": r["threshold"],
                    "target_value": r["target_value"],
                    "duration_mins": r["duration_mins"],
                    "interval_hours": r["interval_hours"],
                    "description": r["description"],
                    "enabled": bool(r["enabled"]),
                    "updated_at": r["updated_at"]
                }
                for r in rows
            ]


# ─── Sensor Readings Database Operations ──────────────────────

async def insert_reading(temperature: float, humidity: float) -> int:
    """
    Insert a new sensor reading into the database.
    Returns the row ID of the inserted record.
    """
    timestamp = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO readings (temperature, humidity, timestamp) VALUES (?, ?, ?)",
            (temperature, humidity, timestamp)
        )
        await db.commit()
        return cursor.lastrowid


async def get_latest_reading():
    """
    Get the most recent sensor reading.
    Returns a dict or None if no readings exist yet.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM readings ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "temperature": row["temperature"],
                    "humidity": row["humidity"],
                    "timestamp": row["timestamp"]
                }
    return None


async def get_recent_readings(limit: int = 100):
    """
    Get the most recent 'limit' readings, newest first.
    Used for the dashboard history table and chart.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM readings ORDER BY id DESC LIMIT ?",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "temperature": row["temperature"],
                    "humidity": row["humidity"],
                    "timestamp": row["timestamp"]
                }
                for row in rows
            ]


async def get_reading_count():
    """Get total number of readings in the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM readings") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


def normalize_timestamp_input(ts: str, is_end: bool = False) -> str:
    """Normalize date/time strings to match ISO timestamp format."""
    if not ts:
        return ts
    ts = ts.strip().replace(" ", "T")
    if len(ts) == 10:  # YYYY-MM-DD
        return f"{ts}T23:59:59.999999" if is_end else f"{ts}T00:00:00"
    if len(ts) == 16:  # YYYY-MM-DDTHH:MM
        return f"{ts}:59.999999" if is_end else f"{ts}:00"
    if len(ts) == 19 and is_end:  # YYYY-MM-DDTHH:MM:SS
        return f"{ts}.999999"
    return ts


async def get_readings_by_range(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    hours: Optional[float] = None,
    limit: Optional[int] = None,
    max_points: int = 1200
) -> Dict[str, Any]:
    """Query readings by relative hours, absolute date range, or limit."""
    conditions = []
    params = []

    if hours is not None and hours > 0:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        conditions.append("timestamp >= ?")
        params.append(cutoff)
    else:
        if start_time:
            norm_start = normalize_timestamp_input(start_time, is_end=False)
            conditions.append("timestamp >= ?")
            params.append(norm_start)
        if end_time:
            norm_end = normalize_timestamp_input(end_time, is_end=True)
            conditions.append("timestamp <= ?")
            params.append(norm_end)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        if limit is not None and not conditions:
            async with db.execute(
                "SELECT * FROM readings ORDER BY id DESC LIMIT ?",
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()

            readings = [
                {
                    "id": r["id"],
                    "temperature": r["temperature"],
                    "humidity": r["humidity"],
                    "timestamp": r["timestamp"]
                }
                for r in rows
            ]

            total_matching = len(readings)

            if readings:
                temps = [r["temperature"] for r in readings]
                humids = [r["humidity"] for r in readings]
                stats = {
                    "min_temp": round(min(temps), 2),
                    "max_temp": round(max(temps), 2),
                    "avg_temp": round(sum(temps) / len(temps), 2),
                    "min_humid": round(min(humids), 2),
                    "max_humid": round(max(humids), 2),
                    "avg_humid": round(sum(humids) / len(humids), 2),
                }
            else:
                stats = {
                    "min_temp": None, "max_temp": None, "avg_temp": None,
                    "min_humid": None, "max_humid": None, "avg_humid": None
                }

            return {
                "readings": readings,
                "count": total_matching,
                "total_matching": total_matching,
                "is_sampled": False,
                "stats": stats
            }

        # Query stats across matched range
        stats_query = f"""
            SELECT 
                COUNT(*) as total_count,
                MIN(temperature) as min_temp,
                MAX(temperature) as max_temp,
                AVG(temperature) as avg_temp,
                MIN(humidity) as min_humid,
                MAX(humidity) as max_humid,
                AVG(humidity) as avg_humid
            FROM readings
            {where_clause}
        """
        async with db.execute(stats_query, params) as cursor:
            stats_row = await cursor.fetchone()
            total_matching = stats_row["total_count"] if stats_row else 0
            stats = {
                "min_temp": round(stats_row["min_temp"], 2) if stats_row and stats_row["min_temp"] is not None else None,
                "max_temp": round(stats_row["max_temp"], 2) if stats_row and stats_row["max_temp"] is not None else None,
                "avg_temp": round(stats_row["avg_temp"], 2) if stats_row and stats_row["avg_temp"] is not None else None,
                "min_humid": round(stats_row["min_humid"], 2) if stats_row and stats_row["min_humid"] is not None else None,
                "max_humid": round(stats_row["max_humid"], 2) if stats_row and stats_row["max_humid"] is not None else None,
                "avg_humid": round(stats_row["avg_humid"], 2) if stats_row and stats_row["avg_humid"] is not None else None,
            }

        if total_matching == 0:
            return {
                "readings": [],
                "count": 0,
                "total_matching": 0,
                "is_sampled": False,
                "stats": stats
            }

        query = f"SELECT * FROM readings {where_clause} ORDER BY id DESC"
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        all_readings = [
            {
                "id": r["id"],
                "temperature": r["temperature"],
                "humidity": r["humidity"],
                "timestamp": r["timestamp"]
            }
            for r in rows
        ]

        is_sampled = False
        if max_points > 0 and len(all_readings) > max_points:
            is_sampled = True
            n = len(all_readings)
            step = (n - 1) / (max_points - 1)
            sampled = [all_readings[int(round(i * step))] for i in range(max_points - 1)]
            sampled.append(all_readings[-1])
            readings = sampled
        else:
            readings = all_readings

        return {
            "readings": readings,
            "count": len(readings),
            "total_matching": total_matching,
            "is_sampled": is_sampled,
            "stats": stats
        }


async def delete_readings(
    clear_all: bool = False,
    hours: Optional[float] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
) -> int:
    """Delete readings from the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        if clear_all:
            async with db.execute("SELECT COUNT(*) FROM readings") as count_cursor:
                row = await count_cursor.fetchone()
                deleted_count = row[0] if row else 0

            await db.execute("DELETE FROM readings")
            try:
                await db.execute("DELETE FROM sqlite_sequence WHERE name='readings'")
            except Exception:
                pass
            await db.commit()
            return deleted_count

        conditions = []
        params = []

        if hours is not None and hours > 0:
            cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
            conditions.append("timestamp >= ?")
            params.append(cutoff)
        else:
            if start_time:
                norm_start = normalize_timestamp_input(start_time, is_end=False)
                conditions.append("timestamp >= ?")
                params.append(norm_start)
            if end_time:
                norm_end = normalize_timestamp_input(end_time, is_end=True)
                conditions.append("timestamp <= ?")
                params.append(norm_end)

        if not conditions:
            return 0

        where_clause = f"WHERE {' AND '.join(conditions)}"

        count_query = f"SELECT COUNT(*) FROM readings {where_clause}"
        async with db.execute(count_query, params) as count_cursor:
            row = await count_cursor.fetchone()
            deleted_count = row[0] if row else 0

        await db.execute(f"DELETE FROM readings {where_clause}", params)
        await db.commit()
        return deleted_count


# ─── Smart Plug Database Operations ───────────────────────────

async def get_recent_readings_for_automation(limit: int = 30) -> List[dict]:
    """Get the most recent 'limit' sensor readings, newest first."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, temperature, humidity, timestamp FROM readings ORDER BY id DESC LIMIT ?",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "temperature": r["temperature"],
                    "humidity": r["humidity"],
                    "timestamp": r["timestamp"]
                }
                for r in rows
            ]


async def upsert_plug_state(
    plug_name: str,
    current_state: str,
    is_verified: bool = False,
    last_successful_check: Optional[str] = None,
    last_attempted_action: Optional[str] = None,
    last_action_result: Optional[str] = None
) -> None:
    """Insert or update the current state record for a smart plug."""
    now_iso = datetime.now().isoformat()
    verified_int = 1 if is_verified else 0

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM smart_plug_state WHERE plug_name = ?", (plug_name,)) as cursor:
            existing = await cursor.fetchone()

        if existing:
            succ_check = last_successful_check or existing["last_successful_check"]
            attempt_act = last_attempted_action or existing["last_attempted_action"]
            act_res = last_action_result or existing["last_action_result"]

            await db.execute("""
                UPDATE smart_plug_state
                SET current_state = ?,
                    is_verified = ?,
                    last_successful_check = ?,
                    last_attempted_action = ?,
                    last_action_result = ?,
                    updated_at = ?
                WHERE plug_name = ?
            """, (current_state, verified_int, succ_check, attempt_act, act_res, now_iso, plug_name))
        else:
            await db.execute("""
                INSERT INTO smart_plug_state (
                    plug_name, current_state, is_verified,
                    last_successful_check, last_attempted_action,
                    last_action_result, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (plug_name, current_state, verified_int, last_successful_check, last_attempted_action, last_action_result, now_iso))

        await db.commit()


async def get_plug_state_record(plug_name: str) -> Optional[dict]:
    """Get the current state record of a specific plug."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM smart_plug_state WHERE plug_name = ?",
            (plug_name.lower().strip(),)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "plug_name": row["plug_name"],
                    "current_state": row["current_state"],
                    "is_verified": bool(row["is_verified"]),
                    "last_successful_check": row["last_successful_check"],
                    "last_attempted_action": row["last_attempted_action"],
                    "last_action_result": row["last_action_result"],
                    "updated_at": row["updated_at"]
                }
    return None


async def get_all_plug_states() -> List[dict]:
    """Get state records for all registered smart plugs."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM smart_plug_state ORDER BY plug_name ASC") as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "plug_name": r["plug_name"],
                    "current_state": r["current_state"],
                    "is_verified": bool(r["is_verified"]),
                    "last_successful_check": r["last_successful_check"],
                    "last_attempted_action": r["last_attempted_action"],
                    "last_action_result": r["last_action_result"],
                    "updated_at": r["updated_at"]
                }
                for r in rows
            ]


async def insert_plug_history(
    plug_name: str,
    plug_ip: Optional[str],
    requested_action: str,
    previous_state: Optional[str],
    resulting_state: Optional[str],
    success: bool,
    trigger_source: str,
    temperature: Optional[float] = None,
    humidity: Optional[float] = None,
    sensor_readings_count: Optional[int] = None,
    reason: Optional[str] = None,
    error_message: Optional[str] = None
) -> int:
    """Record an action attempt in smart_plug_history."""
    now_iso = datetime.now().isoformat()
    success_int = 1 if success else 0

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO smart_plug_history (
                plug_name, plug_ip, requested_action,
                previous_state, resulting_state, success,
                trigger_source, temperature, humidity,
                sensor_readings_count, reason, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            plug_name, plug_ip, requested_action,
            previous_state, resulting_state, success_int,
            trigger_source, temperature, humidity,
            sensor_readings_count, reason, error_message, now_iso
        ))
        await db.commit()
        return cursor.lastrowid


async def get_plug_history_records(
    plug_name: Optional[str] = None,
    limit: int = 50,
    hours: Optional[float] = None
) -> List[dict]:
    """Retrieve history records for smart plug actions (newest first)."""
    conditions = []
    params = []

    if plug_name:
        conditions.append("plug_name = ?")
        params.append(plug_name.lower().strip())

    if hours is not None and hours > 0:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        conditions.append("created_at >= ?")
        params.append(cutoff)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM smart_plug_history {where_clause} ORDER BY id DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "plug_name": r["plug_name"],
                    "plug_ip": r["plug_ip"],
                    "requested_action": r["requested_action"],
                    "previous_state": r["previous_state"],
                    "resulting_state": r["resulting_state"],
                    "success": bool(r["success"]),
                    "trigger_source": r["trigger_source"],
                    "temperature": r["temperature"],
                    "humidity": r["humidity"],
                    "sensor_readings_count": r["sensor_readings_count"],
                    "reason": r["reason"],
                    "error_message": r["error_message"],
                    "created_at": r["created_at"]
                }
                for r in rows
            ]


async def get_plug_timeline_events(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    hours: Optional[float] = None
) -> List[dict]:
    """Get plug events ordered chronologically (oldest first)."""
    conditions = []
    params = []

    if hours is not None and hours > 0:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        conditions.append("created_at >= ?")
        params.append(cutoff)
    else:
        if start_time:
            norm_start = normalize_timestamp_input(start_time, is_end=False)
            conditions.append("created_at >= ?")
            params.append(norm_start)
        if end_time:
            norm_end = normalize_timestamp_input(end_time, is_end=True)
            conditions.append("created_at <= ?")
            params.append(norm_end)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM smart_plug_history {where_clause} ORDER BY created_at ASC"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "plug_name": r["plug_name"],
                    "requested_action": r["requested_action"],
                    "resulting_state": r["resulting_state"],
                    "success": bool(r["success"]),
                    "trigger_source": r["trigger_source"],
                    "temperature": r["temperature"],
                    "humidity": r["humidity"],
                    "reason": r["reason"],
                    "created_at": r["created_at"]
                }
                for r in rows
            ]
