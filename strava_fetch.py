"""
Strava Data Fetcher — run this daily (or let the scheduled task handle it).
Refreshes your access token and downloads all Run activities from Strava,
saving them to activities.json for the dashboard.

Usage:
    python strava_fetch.py
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CONFIG_FILE     = "strava_config.json"
ACTIVITIES_FILE = "activities.json"
API_BASE        = "https://www.strava.com/api/v3"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(
            f"'{CONFIG_FILE}' not found.\n"
            "Please run strava_setup.py first to authorize your account."
        )
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def refresh_token_if_needed(config):
    """Refresh the access token if it has expired (or will expire soon)."""
    if time.time() > config["expires_at"] - 300:
        print("Access token expired — refreshing...")
        url = "https://www.strava.com/oauth/token"
        data = urllib.parse.urlencode({
            "client_id":     config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type":    "refresh_token",
            "refresh_token": config["refresh_token"],
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
        config["access_token"]  = tokens["access_token"]
        config["refresh_token"] = tokens["refresh_token"]
        config["expires_at"]    = tokens["expires_at"]
        save_config(config)
        print("✓ Token refreshed.")
    return config


def api_get(endpoint, token, params=None):
    url = f"{API_BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_all_activities(token):
    """Fetch all activities with pagination (Strava returns max 200 per page)."""
    all_activities = []
    page = 1
    print("Fetching activities from Strava", end="", flush=True)
    while True:
        batch = api_get("/athlete/activities", token, {
            "per_page": 200,
            "page": page,
        })
        if not batch:
            break
        all_activities.extend(batch)
        print(".", end="", flush=True)
        page += 1
        if len(batch) < 200:
            break
        time.sleep(0.3)  # be polite to the API
    print(f" done. ({len(all_activities)} total activities)")
    return all_activities


def meters_to_km(m):
    return round(m / 1000, 2)


def pace_min_per_km(speed_mps):
    """Convert m/s to pace in decimal minutes/km (e.g. 5.5 = 5:30/km)."""
    if not speed_mps or speed_mps == 0:
        return None
    pace_s_per_km = 1000 / speed_mps
    return round(pace_s_per_km / 60, 4)


def format_pace(pace_decimal):
    """Convert decimal pace to MM:SS string."""
    if pace_decimal is None:
        return None
    minutes = int(pace_decimal)
    seconds = round((pace_decimal - minutes) * 60)
    return f"{minutes}:{seconds:02d}"


def process_activity(a):
    """Extract relevant fields from a raw Strava activity."""
    distance_km = meters_to_km(a.get("distance", 0))
    speed       = a.get("average_speed", 0)
    pace        = pace_min_per_km(speed)

    return {
        "id":             a["id"],
        "name":           a.get("name", ""),
        "type":           a.get("type", ""),
        "sport_type":     a.get("sport_type", a.get("type", "")),
        "date":           a.get("start_date_local", "")[:10],
        "datetime":       a.get("start_date_local", ""),
        "distance_km":    distance_km,
        "moving_time_s":  a.get("moving_time", 0),
        "elapsed_time_s": a.get("elapsed_time", 0),
        "pace_decimal":   pace,
        "pace_str":       format_pace(pace),
        "avg_speed_mps":  speed,
        "avg_heartrate":  a.get("average_heartrate"),
        "max_heartrate":  a.get("max_heartrate"),
        "elevation_gain": round(a.get("total_elevation_gain", 0), 1),
        "avg_cadence":    a.get("average_cadence"),
        "suffer_score":   a.get("suffer_score"),
        "calories":       a.get("calories"),
        "kudos_count":    a.get("kudos_count", 0),
        "map_polyline":   a.get("map", {}).get("summary_polyline", ""),
    }


def main():
    print("\n=== Strava Running Dashboard — Fetch Data ===\n")

    config = load_config()
    config = refresh_token_if_needed(config)
    token  = config["access_token"]

    raw_activities = fetch_all_activities(token)

    # Process and filter (keep all types for now — dashboard filters to runs)
    processed = [process_activity(a) for a in raw_activities]
    processed.sort(key=lambda x: x["date"], reverse=True)

    run_count   = sum(1 for a in processed if "run" in a["sport_type"].lower() or "run" in a["type"].lower())
    total_km    = sum(a["distance_km"] for a in processed if "run" in a["sport_type"].lower() or "run" in a["type"].lower())

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "athlete_name": config.get("athlete_name", "Athlete"),
        "total_runs":   run_count,
        "total_km":     round(total_km, 1),
        "activities":   processed,
    }

    with open(ACTIVITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Saved {len(processed)} activities to {ACTIVITIES_FILE}")
    print(f"  Runs: {run_count}  |  Total km: {total_km:.1f} km")
    print(f"\nOpen your dashboard: http://localhost:8080  (run serve.py first)")


if __name__ == "__main__":
    main()
