#!/usr/bin/env python3
"""Sync Garmin Connect activities and daily wellness data into SQLite.

First run asks for email/password (and an MFA code if enabled); tokens are
then cached in ~/.garminconnect so later runs need no password.
"""

import argparse
import getpass
import io
import json
import logging
import os
import sqlite3
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

TOKENSTORE = os.getenv("GARMINTOKENS", "~/.garminconnect")
OVERLAP_DAYS = 2
DEFAULT_BACKFILL_DAYS = 30

log = logging.getLogger("garmin_sync")

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id     INTEGER PRIMARY KEY,
    start_time      TEXT,
    activity_type   TEXT,
    name            TEXT,
    distance_m      REAL,
    duration_s      REAL,
    moving_s        REAL,
    elevation_gain_m REAL,
    elevation_loss_m REAL,
    avg_hr          REAL,
    max_hr          REAL,
    avg_power       REAL,
    norm_power      REAL,
    max_power       REAL,
    calories        REAL,
    fit_path        TEXT,
    raw_json        TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily (
    day             TEXT PRIMARY KEY,
    resting_hr      INTEGER,
    steps           INTEGER,
    avg_stress      INTEGER,
    max_stress      INTEGER,
    body_battery_high INTEGER,
    body_battery_low  INTEGER,
    body_battery_charged INTEGER,
    body_battery_drained INTEGER,
    sleep_seconds   INTEGER,
    deep_sleep_s    INTEGER,
    light_sleep_s   INTEGER,
    rem_sleep_s     INTEGER,
    awake_s         INTEGER,
    sleep_score     INTEGER,
    summary_json    TEXT,
    sleep_json      TEXT,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def login() -> Garmin:
    tokenstore = str(Path(TOKENSTORE).expanduser())
    try:
        api = Garmin()
        api.login(tokenstore)
        return api
    except (GarminConnectAuthenticationError, FileNotFoundError):
        log.info("No valid cached tokens, logging in with credentials")

    if not sys.stdin.isatty() and not os.getenv("GARMIN_EMAIL"):
        raise GarminConnectAuthenticationError(
            "no cached tokens and no terminal; run once interactively first"
        )
    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ")
    password = os.getenv("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    api = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("MFA code: ").strip(),
    )
    Path(tokenstore).mkdir(mode=0o700, parents=True, exist_ok=True)
    api.login(tokenstore)
    log.info("Logged in; tokens saved to %s", tokenstore)
    return api


def get_meta(db, key):
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(db, key, value):
    db.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def download_fit(api: Garmin, activity_id: int, fit_dir: Path) -> str | None:
    target = fit_dir / f"{activity_id}.fit"
    if target.exists():
        return str(target)
    data = api.download_activity(
        str(activity_id), dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL
    )
    # ORIGINAL comes back as a zip holding the .fit file.
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
        if not fit_names:
            log.warning("Activity %s: no FIT file in download", activity_id)
            return None
        target.write_bytes(zf.read(fit_names[0]))
    return str(target)


def sync_activities(api, db, start: date, end: date, fit_dir: Path | None):
    activities = api.get_activities_by_date(start.isoformat(), end.isoformat())
    for a in activities:
        aid = a["activityId"]
        fit_path = None
        if fit_dir is not None:
            try:
                fit_path = download_fit(api, aid, fit_dir)
            except Exception as e:  # keep syncing other activities
                log.warning("Activity %s: FIT download failed: %s", aid, e)
        db.execute(
            """
            INSERT INTO activities (
                activity_id, start_time, activity_type, name, distance_m,
                duration_s, moving_s, elevation_gain_m, elevation_loss_m,
                avg_hr, max_hr, avg_power, norm_power, max_power, calories,
                fit_path, raw_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                start_time = excluded.start_time,
                activity_type = excluded.activity_type,
                name = excluded.name,
                distance_m = excluded.distance_m,
                duration_s = excluded.duration_s,
                moving_s = excluded.moving_s,
                elevation_gain_m = excluded.elevation_gain_m,
                elevation_loss_m = excluded.elevation_loss_m,
                avg_hr = excluded.avg_hr,
                max_hr = excluded.max_hr,
                avg_power = excluded.avg_power,
                norm_power = excluded.norm_power,
                max_power = excluded.max_power,
                calories = excluded.calories,
                fit_path = COALESCE(excluded.fit_path, activities.fit_path),
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            (
                aid,
                a.get("startTimeLocal"),
                (a.get("activityType") or {}).get("typeKey"),
                a.get("activityName"),
                a.get("distance"),
                a.get("duration"),
                a.get("movingDuration"),
                a.get("elevationGain"),
                a.get("elevationLoss"),
                a.get("averageHR"),
                a.get("maxHR"),
                a.get("avgPower"),
                a.get("normPower"),
                a.get("maxPower"),
                a.get("calories"),
                fit_path,
                json.dumps(a),
                now_iso(),
            ),
        )
    log.info("Activities: %d synced (%s .. %s)", len(activities), start, end)


def sync_day(api, db, day: date):
    d = day.isoformat()
    summary = api.get_user_summary(d) or {}
    sleep = api.get_sleep_data(d) or {}
    sleep_dto = sleep.get("dailySleepDTO") or {}
    sleep_score = (
        ((sleep_dto.get("sleepScores") or {}).get("overall") or {}).get("value")
    )
    db.execute(
        """
        INSERT INTO daily (
            day, resting_hr, steps, avg_stress, max_stress,
            body_battery_high, body_battery_low, body_battery_charged,
            body_battery_drained, sleep_seconds, deep_sleep_s, light_sleep_s,
            rem_sleep_s, awake_s, sleep_score, summary_json, sleep_json,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(day) DO UPDATE SET
            resting_hr = excluded.resting_hr,
            steps = excluded.steps,
            avg_stress = excluded.avg_stress,
            max_stress = excluded.max_stress,
            body_battery_high = excluded.body_battery_high,
            body_battery_low = excluded.body_battery_low,
            body_battery_charged = excluded.body_battery_charged,
            body_battery_drained = excluded.body_battery_drained,
            sleep_seconds = excluded.sleep_seconds,
            deep_sleep_s = excluded.deep_sleep_s,
            light_sleep_s = excluded.light_sleep_s,
            rem_sleep_s = excluded.rem_sleep_s,
            awake_s = excluded.awake_s,
            sleep_score = excluded.sleep_score,
            summary_json = excluded.summary_json,
            sleep_json = excluded.sleep_json,
            updated_at = excluded.updated_at
        """,
        (
            d,
            summary.get("restingHeartRate"),
            summary.get("totalSteps"),
            summary.get("averageStressLevel"),
            summary.get("maxStressLevel"),
            summary.get("bodyBatteryHighestValue"),
            summary.get("bodyBatteryLowestValue"),
            summary.get("bodyBatteryChargedValue"),
            summary.get("bodyBatteryDrainedValue"),
            sleep_dto.get("sleepTimeSeconds"),
            sleep_dto.get("deepSleepSeconds"),
            sleep_dto.get("lightSleepSeconds"),
            sleep_dto.get("remSleepSeconds"),
            sleep_dto.get("awakeSleepSeconds"),
            sleep_score,
            json.dumps(summary),
            json.dumps(sleep),
            now_iso(),
        ),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="garmin.db", help="SQLite path (default: garmin.db)")
    p.add_argument("--fit", action="store_true", help="also download original FIT files")
    p.add_argument("--fit-dir", default="fit", help="where to store FIT files (default: fit/)")
    p.add_argument("--days", type=int, help="sync the last N days, ignoring saved state")
    p.add_argument("--since", help="sync from YYYY-MM-DD, ignoring saved state")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)

    today = date.today()
    if args.since:
        start = date.fromisoformat(args.since)
    elif args.days:
        start = today - timedelta(days=args.days)
    elif last := get_meta(db, "last_sync_day"):
        # Re-fetch a couple of days back to catch late watch syncs.
        start = date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)
    else:
        start = today - timedelta(days=DEFAULT_BACKFILL_DAYS)

    fit_dir = None
    if args.fit:
        fit_dir = Path(args.fit_dir)
        fit_dir.mkdir(parents=True, exist_ok=True)

    try:
        api = login()
        sync_activities(api, db, start, today, fit_dir)
        db.commit()

        day = start
        while day <= today:
            try:
                sync_day(api, db, day)
                db.commit()
            except GarminConnectConnectionError as e:
                log.warning("Daily %s failed: %s", day, e)
            day += timedelta(days=1)
        log.info("Daily: %s .. %s synced", start, today)

        set_meta(db, "last_sync_day", today.isoformat())
        db.commit()
    except GarminConnectTooManyRequestsError:
        log.error("Rate limited by Garmin; try again later")
        sys.exit(2)
    except GarminConnectAuthenticationError as e:
        log.error("Authentication failed: %s", e)
        sys.exit(3)
    finally:
        db.close()


if __name__ == "__main__":
    main()
