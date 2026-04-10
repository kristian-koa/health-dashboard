"""
Whoop Data Fetcher — run daily (or let the scheduled task handle it).
Refreshes your access token and downloads recovery, sleep, strain, and
workout data from Whoop, saving to whoop_data.json for the dashboard.

Usage:
    python whoop_fetch.py
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE     = os.path.join(SCRIPT_DIR, "whoop_config.json")
DATA_FILE       = os.path.join(SCRIPT_DIR, "whoop_data.json")
API_BASE        = "https://api.prod.whoop.com/developer/v2"
TOKEN_URL       = "https://api.prod.whoop.com/oauth/oauth2/token"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(
            f"'{CONFIG_FILE}' not found.\n"
            "Run whoop_setup.py first to authorize your account."
        )
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def refresh_token_if_needed(config):
    """Refresh the access token if expired or about to expire."""
    if not config.get("access_token"):
        raise RuntimeError("No access token. Run whoop_setup.py first.")

    if time.time() > config.get("expires_at", 0) - 300:
        print("Access token expired — refreshing...")
        data = urllib.parse.urlencode({
            "grant_type":    "refresh_token",
            "refresh_token": config["refresh_token"],
            "client_id":     config["client_id"],
            "client_secret": config["client_secret"],
        }).encode()

        req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                     headers={"User-Agent": "WhoopDashboard/1.0"})
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())

        config["access_token"]  = tokens["access_token"]
        config["refresh_token"] = tokens.get("refresh_token", config["refresh_token"])
        config["expires_at"]    = int(time.time()) + tokens.get("expires_in", 3600)
        save_config(config)
        print("Token refreshed.")
    return config


def api_get(endpoint, token, params=None):
    """Make an authenticated GET request to the Whoop API."""
    url = f"{API_BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "WhoopDashboard/1.0",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_paginated(endpoint, token, start_date=None, end_date=None):
    """Fetch all records from a paginated Whoop endpoint."""
    all_records = []
    params = {"limit": 25}
    if start_date:
        params["start"] = start_date
    if end_date:
        params["end"] = end_date

    print(f"  Fetching {endpoint}", end="", flush=True)
    while True:
        data = api_get(endpoint, token, params)
        records = data.get("records", [])
        all_records.extend(records)
        print(".", end="", flush=True)

        next_token = data.get("next_token")
        if not next_token or not records:
            break
        params["nextToken"] = next_token
        time.sleep(0.3)

    print(f" ({len(all_records)})")
    return all_records


def process_recovery(rec):
    """Extract key fields from a recovery record."""
    score = rec.get("score") or {}
    return {
        "cycle_id":           rec.get("cycle_id"),
        "created_at":         rec.get("created_at"),
        "updated_at":         rec.get("updated_at"),
        "recovery_score":     score.get("recovery_score"),
        "resting_heart_rate": score.get("resting_heart_rate"),
        "hrv_rmssd":          score.get("hrv_rmssd_milli"),
        "spo2_pct":           score.get("spo2_percentage"),
        "skin_temp_celsius":  score.get("skin_temp_celsius"),
    }


def process_sleep(rec):
    """Extract key fields from a sleep record."""
    score = rec.get("score") or {}
    return {
        "id":                    rec.get("id"),
        "start":                 rec.get("start"),
        "end":                   rec.get("end"),
        "nap":                   rec.get("nap", False),
        "performance_pct":       score.get("stage_summary", {}).get("total_in_bed_time_milli"),
        "sleep_efficiency_pct":  score.get("sleep_efficiency_percentage"),
        "sleep_consistency_pct": score.get("sleep_consistency_percentage"),
        "respiratory_rate":      score.get("respiratory_rate"),
        "total_in_bed_ms":       score.get("stage_summary", {}).get("total_in_bed_time_milli"),
        "total_awake_ms":        score.get("stage_summary", {}).get("total_awake_time_milli"),
        "total_light_ms":        score.get("stage_summary", {}).get("total_light_sleep_time_milli"),
        "total_slow_wave_ms":    score.get("stage_summary", {}).get("total_slow_wave_sleep_time_milli"),
        "total_rem_ms":          score.get("stage_summary", {}).get("total_rem_sleep_time_milli"),
        "sleep_needed_ms":       score.get("sleep_needed", {}).get("baseline_milli"),
        "sleep_debt_ms":         score.get("sleep_needed", {}).get("debt_milli"),
    }


def process_cycle(rec):
    """Extract key fields from a cycle (daily strain) record."""
    score = rec.get("score") or {}
    return {
        "id":        rec.get("id"),
        "start":     rec.get("start"),
        "end":       rec.get("end"),
        "strain":    score.get("strain"),
        "kilojoule": score.get("kilojoule"),
        "avg_hr":    score.get("average_heart_rate"),
        "max_hr":    score.get("max_heart_rate"),
    }


def process_workout(rec):
    """Extract key fields from a workout record."""
    score = rec.get("score") or {}
    return {
        "id":              rec.get("id"),
        "start":           rec.get("start"),
        "end":             rec.get("end"),
        "sport_id":        rec.get("sport_id"),
        "sport_name":      get_sport_name(rec.get("sport_id")),
        "strain":          score.get("strain"),
        "avg_hr":          score.get("average_heart_rate"),
        "max_hr":          score.get("max_heart_rate"),
        "kilojoule":       score.get("kilojoule"),
        "distance_meter":  score.get("distance_meter"),
        "zone_durations":  score.get("zone_duration", {}),
    }


# Common Whoop sport IDs
SPORT_NAMES = {
    -1: "Activity", 0: "Running", 1: "Cycling", 16: "Baseball",
    17: "Basketball", 18: "Rowing", 19: "Fencing", 20: "Field Hockey",
    21: "Football", 22: "Golf", 24: "Ice Hockey", 25: "Lacrosse",
    27: "Rugby", 28: "Sailing", 29: "Skiing", 30: "Soccer",
    31: "Softball", 32: "Squash", 33: "Swimming", 34: "Tennis",
    35: "Track & Field", 36: "Volleyball", 37: "Water Polo",
    38: "Wrestling", 39: "Boxing", 42: "Dance", 43: "Pilates",
    44: "Yoga", 45: "Weightlifting", 47: "Cross Country Skiing",
    48: "Functional Fitness", 49: "Duathlon", 51: "Gymnastics",
    52: "Hiking/Rucking", 53: "Horseback Riding", 55: "Kayaking",
    56: "Martial Arts", 57: "Mountain Biking", 59: "Paddleboarding",
    60: "Snowboarding", 61: "Surfing", 62: "Triathlon",
    63: "Walking", 64: "Wheelchair Pushing", 65: "Assault Bike",
    66: "Elliptical", 70: "Spinning", 71: "Stairmaster",
    73: "HIIT", 74: "Meditation", 75: "Other", 76: "Diving",
    77: "Operations - Tactical", 82: "Pickleball", 83: "Ski Ergometer",
    84: "Climber", 85: "Jump Rope",
}


def get_sport_name(sport_id):
    return SPORT_NAMES.get(sport_id, f"Sport {sport_id}")


def ms_to_hours(ms):
    if ms is None:
        return None
    return round(ms / 3600000, 2)


def main():
    print("\n=== Whoop Data Fetcher ===\n")

    config = load_config()
    config = refresh_token_if_needed(config)
    token  = config["access_token"]

    # Fetch profile
    print("Fetching profile...")
    profile = api_get("/user/profile/basic", token)
    body    = api_get("/user/measurement/body", token)

    # Fetch data — last 90 days by default
    end_date   = datetime.now(timezone.utc).isoformat()
    start_date = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()

    recoveries = fetch_paginated("/recovery", token, start_date, end_date)
    sleeps     = fetch_paginated("/activity/sleep", token, start_date, end_date)
    cycles     = fetch_paginated("/cycle", token, start_date, end_date)
    workouts   = fetch_paginated("/activity/workout", token, start_date, end_date)

    # Process
    processed_recoveries = [process_recovery(r) for r in recoveries]
    processed_sleeps     = [process_sleep(s) for s in sleeps]
    processed_cycles     = [process_cycle(c) for c in cycles]
    processed_workouts   = [process_workout(w) for w in workouts]

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "first_name": profile.get("first_name", ""),
            "last_name":  profile.get("last_name", ""),
            "email":      profile.get("email", ""),
        },
        "body": {
            "height_meter":    body.get("height_meter"),
            "weight_kg":       body.get("weight_kilogram"),
            "max_heart_rate":  body.get("max_heart_rate"),
        },
        "summary": {
            "days":           len(processed_cycles),
            "avg_recovery":   round(sum(r["recovery_score"] for r in processed_recoveries if r["recovery_score"] is not None) / max(1, len([r for r in processed_recoveries if r["recovery_score"] is not None])), 1),
            "avg_hrv":        round(sum(r["hrv_rmssd"] for r in processed_recoveries if r["hrv_rmssd"] is not None) / max(1, len([r for r in processed_recoveries if r["hrv_rmssd"] is not None])), 1),
            "avg_rhr":        round(sum(r["resting_heart_rate"] for r in processed_recoveries if r["resting_heart_rate"] is not None) / max(1, len([r for r in processed_recoveries if r["resting_heart_rate"] is not None])), 1),
            "total_workouts": len(processed_workouts),
        },
        "recoveries": processed_recoveries,
        "sleeps":     processed_sleeps,
        "cycles":     processed_cycles,
        "workouts":   processed_workouts,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {DATA_FILE}")
    print(f"  Recoveries: {len(processed_recoveries)}")
    print(f"  Sleeps:     {len(processed_sleeps)}")
    print(f"  Cycles:     {len(processed_cycles)}")
    print(f"  Workouts:   {len(processed_workouts)}")
    print(f"\nAvg Recovery: {output['summary']['avg_recovery']}%")
    print(f"Avg HRV:      {output['summary']['avg_hrv']} ms")
    print(f"Avg RHR:      {output['summary']['avg_rhr']} bpm")


if __name__ == "__main__":
    main()
