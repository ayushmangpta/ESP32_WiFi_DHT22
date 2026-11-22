"""
Database module for ESP32 DHT22 Sensor Logger.

Uses aiosqlite for async SQLite operations.
The database file (sensor_data.db) is created automatically
in the server/ directory. Restarting the server does NOT erase data.
"""

import aiosqlite
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

# Database file path — same directory as this script
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sensor_data.db")


async def init_db():
    """
    Create the database tables if they don't exist:
    - 'readings': ESP32 DHT22 sensor readings
    - 'smart_plug_state': Current verified / last known state of each plug
    - 'smart_plug_history': Audit log of all manual and automated plug commands
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

        await db.commit()
    print(f"✓ Database ready at: {DB_PATH}")


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
    """
    Query readings by relative hours, absolute date range, or limit.
    Includes aggregation statistics and intelligent sampling when data is large.
    """
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

        # If limit is specified and no time filters were provided, fetch latest `limit`
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

        # Query stats across the matched range
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

        # Query all matching readings (ordered newest first, matching API convention)
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
    """
    Delete readings from the database.
    Supports:
      - clear_all: delete all readings
      - hours: delete readings newer than (now - hours) [e.g. last 1h or last 24h]
      - start_time and/or end_time: delete readings within custom date range
    Returns number of deleted rows.
    """
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

        # Count rows to be deleted
        count_query = f"SELECT COUNT(*) FROM readings {where_clause}"
        async with db.execute(count_query, params) as count_cursor:
            row = await count_cursor.fetchone()
            deleted_count = row[0] if row else 0

        await db.execute(f"DELETE FROM readings {where_clause}", params)
        await db.commit()
        return deleted_count


# ─── Smart Plug Database Operations ───

async def get_recent_readings_for_automation(limit: int = 30) -> List[dict]:
    """
    Get the most recent 'limit' sensor readings, newest first.
    Used for 30-reading moving average calculations in automation rules.
    """
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
    """
    Insert or update the current state record for a smart plug.
    """
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
    """
    Get plug events ordered chronologically (oldest first).
    Used to render trigger points on the main chart and plug activity graph.
    """
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



