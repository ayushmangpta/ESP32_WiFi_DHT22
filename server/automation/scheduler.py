"""
Background Scheduler for Timed and Periodic Smart Plug Automation.

Handles:
  1. Water Sprinkler: Scheduled for 5 mins ON once every 2 hours.
  2. Fan (Scheduled): Scheduled for 5 mins ON once every 4 hours.
  3. Fan (Humidity Trigger): Timed 3 mins ON when humidity exceeds threshold (> 96%).

Features:
  - Non-blocking async loop integrated with FastAPI lifespan.
  - Dynamically reads thresholds and intervals from config so UI tweaks apply immediately.
  - Exposes real-time status (next run time, remaining duration, active timers).
  - Provides manual "Run Now" triggers for sprinkler and fan.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from config import get_automation_settings
from services.smart_plug_service import control_plug


class AutomationScheduler:
    """Async background scheduler managing periodic and timed smart plug actions."""

    def __init__(self):
        self._loop_task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Schedule tracking (timestamps)
        self.last_sprinkler_run: Optional[datetime] = None
        self.last_fan_schedule_run: Optional[datetime] = None

        # Active timed operation states
        self.sprinkler_active: bool = False
        self.sprinkler_timer_expires_at: Optional[datetime] = None
        self.sprinkler_reason: str = ""
        self._sprinkler_task: Optional[asyncio.Task] = None

        self.fan_active: bool = False
        self.fan_timer_expires_at: Optional[datetime] = None
        self.fan_reason: str = ""
        self.fan_source: Optional[str] = None  # "scheduled" or "humidity"
        self._fan_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background scheduler loop."""
        if self._running:
            return

        self._running = True
        now = datetime.now()

        # Initialize schedule baselines to now if not set yet
        if self.last_sprinkler_run is None:
            self.last_sprinkler_run = now
        if self.last_fan_schedule_run is None:
            self.last_fan_schedule_run = now

        self._loop_task = asyncio.create_task(self._scheduler_loop())
        print("  ⏰ Background Automation Scheduler started.")

    async def stop(self):
        """Gracefully stop the background scheduler and active timer tasks."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        if self._sprinkler_task and not self._sprinkler_task.done():
            self._sprinkler_task.cancel()
        if self._fan_task and not self._fan_task.done():
            self._fan_task.cancel()

        print("  ⏰ Background Automation Scheduler stopped.")

    async def _scheduler_loop(self):
        """Main periodic check loop running every 5 seconds."""
        # Initial short delay so server startup finishes
        await asyncio.sleep(5)

        while self._running:
            try:
                settings = get_automation_settings()
                if not settings.get("enabled", True):
                    await asyncio.sleep(5)
                    continue

                now = datetime.now()

                # ─── 1. Check Sprinkler Schedule (e.g. Every 2 hours) ───
                sprinkler_interval_hours = settings.get("sprinkler_schedule_interval_hours", 2.0)
                sprinkler_duration_mins = settings.get("sprinkler_schedule_duration_mins", 5.0)

                if self.last_sprinkler_run:
                    next_sprinkler_time = self.last_sprinkler_run + timedelta(hours=sprinkler_interval_hours)
                    if now >= next_sprinkler_time and not self.sprinkler_active:
                        print(f"  ⏰ [Scheduler] Triggering scheduled Sprinkler cycle ({sprinkler_duration_mins}m every {sprinkler_interval_hours}h)")
                        self.trigger_sprinkler_cycle(
                            duration_mins=sprinkler_duration_mins,
                            reason=f"Scheduled irrigation cycle ({sprinkler_duration_mins:.0f}m every {sprinkler_interval_hours:.0f}h)"
                        )

                # ─── 2. Check Fan Periodic Schedule (e.g. Every 4 hours) ───
                fan_interval_hours = settings.get("fan_schedule_interval_hours", 4.0)
                fan_duration_mins = settings.get("fan_schedule_duration_mins", 5.0)

                if self.last_fan_schedule_run:
                    next_fan_time = self.last_fan_schedule_run + timedelta(hours=fan_interval_hours)
                    if now >= next_fan_time and not self.fan_active:
                        print(f"  ⏰ [Scheduler] Triggering scheduled Fan ventilation cycle ({fan_duration_mins}m every {fan_interval_hours}h)")
                        self.trigger_fan_cycle(
                            duration_mins=fan_duration_mins,
                            reason=f"Scheduled ventilation cycle ({fan_duration_mins:.0f}m every {fan_interval_hours:.0f}h)",
                            source="scheduled"
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"  ❌ [Scheduler Loop Error]: {e}")

            await asyncio.sleep(5)

    # ─── Sprinkler Control ─────────────────────────────────────

    def trigger_sprinkler_cycle(self, duration_mins: float, reason: str = "Scheduled irrigation") -> bool:
        """Trigger sprinkler ON for specified minutes, then auto-OFF."""
        if self.sprinkler_active and self._sprinkler_task and not self._sprinkler_task.done():
            # Already active; extend duration if new duration is longer
            new_expiry = datetime.now() + timedelta(minutes=duration_mins)
            if self.sprinkler_timer_expires_at and new_expiry > self.sprinkler_timer_expires_at:
                self.sprinkler_timer_expires_at = new_expiry
                self.sprinkler_reason = reason
            return False

        self.last_sprinkler_run = datetime.now()
        self._sprinkler_task = asyncio.create_task(self._run_sprinkler_task(duration_mins, reason))
        return True

    async def _run_sprinkler_task(self, duration_mins: float, reason: str):
        """Asynchronously turn sprinkler ON, sleep duration, then turn OFF."""
        self.sprinkler_active = True
        self.sprinkler_timer_expires_at = datetime.now() + timedelta(minutes=duration_mins)
        self.sprinkler_reason = reason

        try:
            # Turn Sprinkler ON
            await control_plug(
                plug_name="sprinkler",
                action="ON",
                trigger_source="automation",
                reason=reason
            )

            # Wait while checking if expiry changed or was cancelled
            while datetime.now() < self.sprinkler_timer_expires_at:
                remaining = (self.sprinkler_timer_expires_at - datetime.now()).total_seconds()
                await asyncio.sleep(min(remaining, 5.0))

        except asyncio.CancelledError:
            pass
        finally:
            # Turn Sprinkler OFF
            self.sprinkler_active = False
            self.sprinkler_timer_expires_at = None
            try:
                await control_plug(
                    plug_name="sprinkler",
                    action="OFF",
                    trigger_source="automation",
                    reason=f"Timer elapsed ({reason})"
                )
            except Exception as e:
                print(f"  ❌ [Scheduler] Error turning off sprinkler: {e}")

    # ─── Fan Control (Scheduled or Humidity-Triggered) ──────────

    def trigger_fan_humidity_cycle(self, duration_mins: float, reason: str) -> bool:
        """Trigger fan ON for specified minutes due to high humidity (> 96%)."""
        return self.trigger_fan_cycle(duration_mins=duration_mins, reason=reason, source="humidity")

    def trigger_fan_cycle(self, duration_mins: float, reason: str, source: str = "scheduled") -> bool:
        """Trigger fan ON for specified minutes, then auto-OFF."""
        now = datetime.now()
        new_expiry = now + timedelta(minutes=duration_mins)

        if source == "scheduled":
            self.last_fan_schedule_run = now

        if self.fan_active and self._fan_task and not self._fan_task.done():
            # If already running, extend timer if new duration expires later
            if self.fan_timer_expires_at and new_expiry > self.fan_timer_expires_at:
                self.fan_timer_expires_at = new_expiry
                self.fan_reason = reason
                self.fan_source = source
            return False

        self._fan_task = asyncio.create_task(self._run_fan_task(duration_mins, reason, source))
        return True

    async def _run_fan_task(self, duration_mins: float, reason: str, source: str):
        """Asynchronously turn fan ON, sleep duration, then turn OFF."""
        self.fan_active = True
        self.fan_timer_expires_at = datetime.now() + timedelta(minutes=duration_mins)
        self.fan_reason = reason
        self.fan_source = source

        try:
            # Turn Fan ON
            await control_plug(
                plug_name="fan",
                action="ON",
                trigger_source="automation",
                reason=reason
            )

            # Wait until timer expires
            while datetime.now() < self.fan_timer_expires_at:
                remaining = (self.fan_timer_expires_at - datetime.now()).total_seconds()
                await asyncio.sleep(min(remaining, 5.0))

        except asyncio.CancelledError:
            pass
        finally:
            self.fan_active = False
            self.fan_timer_expires_at = None
            self.fan_source = None
            try:
                await control_plug(
                    plug_name="fan",
                    action="OFF",
                    trigger_source="automation",
                    reason=f"Timer elapsed ({reason})"
                )
            except Exception as e:
                print(f"  ❌ [Scheduler] Error turning off fan: {e}")

    # ─── Status Reporting ──────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return the current scheduler state for the UI and API."""
        now = datetime.now()
        settings = get_automation_settings()

        # Sprinkler calculations
        sprinkler_interval_hours = settings.get("sprinkler_schedule_interval_hours", 2.0)
        sprinkler_duration_mins = settings.get("sprinkler_schedule_duration_mins", 5.0)

        next_sprinkler = None
        sprinkler_countdown_seconds = None
        if self.last_sprinkler_run:
            next_dt = self.last_sprinkler_run + timedelta(hours=sprinkler_interval_hours)
            next_sprinkler = next_dt.isoformat()
            sprinkler_countdown_seconds = max(0, int((next_dt - now).total_seconds()))

        sprinkler_active_remaining = None
        if self.sprinkler_active and self.sprinkler_timer_expires_at:
            sprinkler_active_remaining = max(0, int((self.sprinkler_timer_expires_at - now).total_seconds()))

        # Fan calculations
        fan_interval_hours = settings.get("fan_schedule_interval_hours", 4.0)
        fan_duration_mins = settings.get("fan_schedule_duration_mins", 5.0)

        next_fan = None
        fan_countdown_seconds = None
        if self.last_fan_schedule_run:
            next_fan_dt = self.last_fan_schedule_run + timedelta(hours=fan_interval_hours)
            next_fan = next_fan_dt.isoformat()
            fan_countdown_seconds = max(0, int((next_fan_dt - now).total_seconds()))

        fan_active_remaining = None
        if self.fan_active and self.fan_timer_expires_at:
            fan_active_remaining = max(0, int((self.fan_timer_expires_at - now).total_seconds()))

        return {
            "scheduler_running": self._running,
            "current_time": now.isoformat(),
            "sprinkler": {
                "active": self.sprinkler_active,
                "interval_hours": sprinkler_interval_hours,
                "duration_mins": sprinkler_duration_mins,
                "last_run": self.last_sprinkler_run.isoformat() if self.last_sprinkler_run else None,
                "next_run": next_sprinkler,
                "countdown_seconds": sprinkler_countdown_seconds,
                "active_remaining_seconds": sprinkler_active_remaining,
                "active_reason": self.sprinkler_reason if self.sprinkler_active else None
            },
            "fan": {
                "active": self.fan_active,
                "interval_hours": fan_interval_hours,
                "duration_mins": fan_duration_mins,
                "last_schedule_run": self.last_fan_schedule_run.isoformat() if self.last_fan_schedule_run else None,
                "next_schedule_run": next_fan,
                "schedule_countdown_seconds": fan_countdown_seconds,
                "active_remaining_seconds": fan_active_remaining,
                "active_source": self.fan_source,
                "active_reason": self.fan_reason if self.fan_active else None
            }
        }


# Global scheduler singleton
scheduler = AutomationScheduler()
