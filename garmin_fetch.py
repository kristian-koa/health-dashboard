"""
Garmin Connect Data Fetcher — run this daily (or via scheduled task).
Downloads all activities from Garmin Connect and saves to garmin_activities.json.

Usage:
    python garmin_fetch.py
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from garminconnect import Garmin

FOLDER          = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE     = os.path.join(FOLDER, "garmin_config.json")
TOKEN_DIR       = os.path.join(FOLDER, ".garmin_tokens")
OUTPUT_FILE     = os.path.join(FOLDER, "garmin_activities.json")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(
            f"'{CONFIG_FILE}' not found.\n"
            "Please run garmin_setup.py first to authenticate."
        )
    with open(CONFIG_FILE) as f:
        return json.load(f)


def connect(config):
    """Create a Garmin client and log in using saved tokens."""
    garmin = Garmin(email=config.get("email", ""))
    garmin.login(tokenstore=config.get("token_dir", TOKEN_DIR))
    return garmin


def fetch_all_activities(garmin):
    """Fetch all activities using pagination (100 at a time)."""
    all_activities = []
    start = 0
    limit = 100
    print("Fetching activities from Garmin Connect", end="", flush=True)

    while True:
        batch = garmin.get_activities(start=start, limit=limit)
        if not batch:
            break
        all_activities.extend(batch)
        print(".", end="", flush=True)
        start += limit
        if len(batch) < limit:
            break
        time.sleep(0.3)

    print(f" done. ({len(all_activities)} total)")
    return all_activities


def meters_to_km(m):
    if m is None:
        return 0
    return round(m / 1000, 2)


def pace_min_per_km(speed_mps):
    """Convert m/s to pace in decimal minutes/km."""
    if not speed_mps or speed_mps == 0:
        return None
    pace_s_per_km = 1000 / speed_mps
    return round(pace_s_per_km / 60, 4)


def format_pace(pace_decimal):
    if pace_decimal is None:
        return None
    minutes = int(pace_decimal)
    seconds = round((pace_decimal - minutes) * 60)
    return f"{minutes}:{seconds:02d}"


def format_duration(seconds):
    """Format seconds into H:MM:SS or M:SS."""
    if not seconds:
        return "0:00"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def process_activity(a):
    """Extract relevant fields from a Garmin activity."""
    distance_km = meters_to_km(a.get("distance"))
    duration_s  = a.get("duration", 0) or 0
    moving_s    = a.get("movingDuration", duration_s) or duration_s

    # Garmin stores speed in m/s in some fields
    avg_speed = a.get("averageSpeed", 0) or 0

    # Calculate pace for running/walking activities
    pace = pace_min_per_km(avg_speed) if avg_speed else None

    # Activity type mapping
    activity_type = a.get("activityType", {})
    type_key = activity_type.get("typeKey", "") if isinstance(activity_type, dict) else str(activity_type)
    parent_type = activity_type.get("parentTypeDTO", {}) if isinstance(activity_type, dict) else {}
    parent_key = parent_type.get("typeKey", "") if isinstance(parent_type, dict) else ""

    return {
        "id":               a.get("activityId"),
        "name":             a.get("activityName", ""),
        "type":             type_key,
        "parent_type":      parent_key,
        "sport_type":       type_key,
        "date":             (a.get("startTimeLocal") or "")[:10],
        "datetime":         a.get("startTimeLocal", ""),
        "distance_km":      distance_km,
        "duration_s":       round(duration_s, 1),
        "moving_time_s":    round(moving_s, 1),
        "duration_str":     format_duration(duration_s),
        "pace_decimal":     pace,
        "pace_str":         format_pace(pace),
        "avg_speed_mps":    avg_speed,
        "avg_heartrate":    a.get("averageHR"),
        "max_heartrate":    a.get("maxHR"),
        "elevation_gain":   round(a.get("elevationGain", 0) or 0, 1),
        "elevation_loss":   round(a.get("elevationLoss", 0) or 0, 1),
        "avg_cadence":      a.get("averageRunningCadenceInStepsPerMinute"),
        "calories":         a.get("calories"),
        "avg_power":        a.get("avgPower"),
        "max_power":        a.get("maxPower"),
        "training_effect_aerobic":   a.get("aerobicTrainingEffect"),
        "training_effect_anaerobic": a.get("anaerobicTrainingEffect"),
        "vo2max":           a.get("vO2MaxValue"),
        "training_load":    a.get("activityTrainingLoad"),
        "steps":            a.get("steps"),
        "laps":             a.get("lapCount"),
        "source":           "garmin",
    }


def main():
    print("\n=== Garmin Connect — Fetch Activities ===\n")

    config = load_config()
    garmin = connect(config)
    print("✓ Logged in to Garmin Connect")

    raw_activities = fetch_all_activities(garmin)

    # Process all activities
    processed = [process_activity(a) for a in raw_activities]
    processed.sort(key=lambda x: x["date"], reverse=True)

    # Stats
    type_counts = {}
    for a in processed:
        t = a["type"] or "unknown"
        type_counts[t] = type_counts.get(t, 0) + 1

    run_count = sum(1 for a in processed if "running" in a["type"].lower() or "run" in a["type"].lower())
    total_run_km = sum(a["distance_km"] for a in processed if "running" in a["type"].lower() or "run" in a["type"].lower())

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source":       "garmin_connect",
        "total_activities": len(processed),
        "total_runs":   run_count,
        "total_run_km": round(total_run_km, 1),
        "activity_types": type_counts,
        "activities":   processed,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Saved {len(processed)} activities to garmin_activities.json")
    print(f"  Runs: {run_count}  |  Total run km: {total_run_km:.1f} km")
    print(f"\nActivity types found:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    print(f"\nOpen your dashboard: http://localhost:8080/garmin.html")


if __name__ == "__main__":
    main()
