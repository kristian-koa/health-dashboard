"""
Garmin Connect Setup — authenticate once, then fetch forever.

This script does the one-time login to Garmin Connect. The garminconnect
library uses the same mobile SSO flow as the official Garmin Connect
Android app, gets a DI OAuth Bearer token, and saves it to disk.

After this runs successfully once:
  - Tokens live in .garmin_tokens/garmin_tokens.json (valid ~1 year)
  - garmin_fetch.py can run any number of times a day without touching
    Garmin's login endpoint at all — it just reads the saved tokens
  - The library auto-refreshes the access token transparently as needed

Re-running this script is idempotent: if valid tokens already exist,
it reuses them and doesn't ask for your password.

Usage:
    python garmin_setup.py

If you need to force a fresh login (e.g. changed password), delete the
.garmin_tokens/ directory and re-run.

Rate-limit note:
    Garmin's login endpoint is protected by Cloudflare and can temporarily
    block an IP that has made too many login attempts. This block only
    affects the initial login — once tokens are saved, fetches go to a
    different host that isn't rate-limited. If you hit a 429 here, the
    script will tell you what to do.
"""

import getpass
import json
import os
import sys

import requests

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

FOLDER      = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(FOLDER, "garmin_config.json")
TOKEN_DIR   = os.path.join(FOLDER, ".garmin_tokens")
TOKEN_FILE  = os.path.join(TOKEN_DIR, "garmin_tokens.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def prompt_mfa():
    """Called by the library if your account has MFA enabled."""
    return input("Enter MFA code from your authenticator app: ").strip()


def fetch_egress_info():
    """Return dict with current public IP info from ipinfo.io, or None."""
    try:
        r = requests.get("https://ipinfo.io/json", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def confirm_egress_ip():
    """Print the PC's current public egress IP and ask the user to confirm
    before sending any credentials to Garmin. This is the pre-flight check
    that prevents us from blindly retrying against a known-blocked IP.

    Returns True if the user confirms (or if we couldn't fetch and they
    want to proceed anyway); False if they want to abort.
    """
    print("\n→ Pre-flight: checking the egress IP Garmin will see...")
    info = fetch_egress_info()
    if not info:
        print("  (could not reach ipinfo.io — can't verify the egress IP)")
        answer = input("  Proceed anyway? [y/N]: ").strip().lower()
        return answer == "y"

    ip      = info.get("ip", "unknown")
    city    = info.get("city", "")
    country = info.get("country", "")
    org     = info.get("org", "")
    print(f"  IP:      {ip}")
    print(f"  Where:   {city}, {country}")
    print(f"  ISP:     {org}")
    print()
    print("  Is this a clean IP that hasn't been rate-limited by Garmin?")
    print("  (If you're running through a VPN, confirm it matches the VPN's exit.)")
    answer = input("  Proceed with login from this IP? [y/N]: ").strip().lower()
    return answer == "y"


def try_saved_tokens(email):
    """If tokens already exist on disk, try to use them without prompting
    for a password. Returns a logged-in Garmin on success, else None."""
    if not os.path.exists(TOKEN_FILE):
        return None

    print(f"→ Found existing tokens at {TOKEN_FILE}")
    print("  Validating (no password needed)...")
    try:
        garmin = Garmin(email=email or "unused@example.com")
        garmin.login(tokenstore=TOKEN_DIR)
        return garmin
    except Exception as e:
        print(f"  Saved tokens didn't work: {e}")
        print("  Falling through to credential login.")
        return None


def login_with_credentials(email, password):
    """Do a fresh credential login and save tokens to disk."""
    garmin = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
    garmin.login(tokenstore=TOKEN_DIR)
    return garmin


def explain_rate_limit():
    """Print actionable guidance when login hits HTTP 429."""
    print()
    print("Garmin's Cloudflare protection has temporarily blocked login")
    print("attempts from this IP. This is NOT because your credentials are")
    print("wrong — it's a network-level throttle on the login endpoint.")
    print()
    print("Important: this block only affects the ONE-TIME login. Once you")
    print("get a successful login, tokens are saved (valid ~1 year) and")
    print("garmin_fetch.py talks to a different endpoint that isn't blocked.")
    print()
    print("Your options, in order of easiest:")
    print()
    print("  1. WAIT and try again later.")
    print("     Rate limits typically clear in 1-72 hours. Do NOT keep")
    print("     retrying — every failed attempt can extend the cooldown.")
    print()
    print("  2. ONE login from a different IP.")
    print("     Phone hotspot, VPN, different WiFi — whatever's convenient.")
    print("     You only need ONE successful login. After tokens are saved,")
    print("     you can disconnect the VPN / hotspot and everything keeps")
    print("     working from your normal network.")
    print()
    print("  3. Pivot to Strava (if running data is all you need).")
    print("     Strava has a proper individual OAuth2 API. Use the existing")
    print("     strava_*.py scripts instead.")


def main():
    print("\n=== Garmin Connect Setup ===\n")

    config = load_config()
    email = config.get("email") or input("Garmin Connect email: ").strip()

    # ---- Step 1: reuse existing tokens if possible -----------------------
    garmin = try_saved_tokens(email)

    # ---- Step 2: otherwise, do a fresh credential login ------------------
    if garmin is None:
        # Pre-flight: make sure we're coming from a clean IP before we send
        # credentials. This prevents blindly burning a login attempt on a
        # known-blocked network.
        if not confirm_egress_ip():
            print("\n✗ Aborted before sending credentials.")
            print("  Reconnect your VPN (or wait for the rate limit to clear)")
            print("  and re-run this script.")
            return 1

        print()
        password = getpass.getpass("Garmin Connect password: ")
        if not password:
            print("✗ Password is required")
            return 1

        print("\n→ Logging in to Garmin Connect...")
        try:
            garmin = login_with_credentials(email, password)
        except Exception as e:
            # Classify by message content, not exception type — the library
            # wraps 429 errors in several different exception classes depending
            # on the code path. Checking the message is more reliable.
            msg = str(e)
            msg_lower = msg.lower()
            if "429" in msg or "rate limit" in msg_lower or "cloudflare" in msg_lower:
                print(f"\n✗ Rate limited: {e}")
                explain_rate_limit()
            elif "invalid" in msg_lower and ("password" in msg_lower or "username" in msg_lower):
                print(f"\n✗ Invalid credentials: {e}")
                print("  Log in at https://connect.garmin.com in a browser to")
                print("  confirm your email and password are correct.")
            elif "mfa" in msg_lower:
                print(f"\n✗ MFA error: {e}")
                print("  If your account has 2FA enabled, make sure the code")
                print("  you typed was correct and not expired.")
            else:
                print(f"\n✗ Login failed: {e}")
            return 1

    print("✓ Authenticated to Garmin Connect")

    # ---- Step 3: persist config (email only — password is NEVER stored) --
    config["email"] = email
    config["token_dir"] = TOKEN_DIR
    save_config(config)
    print(f"✓ Config saved to {CONFIG_FILE}")
    print(f"✓ Tokens at    {TOKEN_FILE}")

    # ---- Step 4: sanity-check the session with a real API call ----------
    print("\n→ Test fetch: last activity...")
    try:
        last = garmin.get_last_activity()
        if last:
            name = last.get("activityName", "Unknown")
            date = last.get("startTimeLocal", "")[:10]
            print(f'✓ "{name}" on {date}')
        else:
            print("✓ Authenticated, but no activities found yet.")
    except Exception as e:
        print(f"⚠ Last-activity fetch failed: {e}")
        print("  (Tokens are saved — garmin_fetch.py may still work.)")

    print("\n✓ Setup complete. Next step: python garmin_fetch.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
