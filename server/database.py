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
    Create the database and the 'readings' table if they don't exist.
    Called once when the server starts up.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                temperature REAL    NOT NULL,
                humidity    REAL    NOT NULL,
                timestamp   TEXT    NOT NULL
            )
        """)
        # Index on timestamp for fast dashboard queries
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_timestamp 
            ON readings (timestamp DESC)
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


