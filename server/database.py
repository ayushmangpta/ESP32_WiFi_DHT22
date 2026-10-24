"""
Database module for ESP32 DHT22 Sensor Logger.

Uses aiosqlite for async SQLite operations.
The database file (sensor_data.db) is created automatically
in the server/ directory. Restarting the server does NOT erase data.
"""

import aiosqlite
import os
from datetime import datetime

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
