"""
Garmin Connect Setup — run this once to authenticate and save your session.

Usage:
    python garmin_setup.py

You'll be prompted for your Garmin Connect email and password.
If you have MFA enabled, you'll be asked for the code too.
Tokens are saved locally so you won't need to log in again (until they expire).
"""

import json
import os
import getpass
from garminconnect import Garmin

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "garmin_config.json")
TOKEN_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".garmin_tokens")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_mfa():
    """Prompt for MFA code if Garmin account has 2FA enabled."""
    return input("Enter MFA code from your authenticator app: ")


def main():
    print("\n=== Garmin Connect Setup ===\n")

    config = load_config()

    email = config.get("email") or input("Garmin Connect email: ").strip()
    password = getpass.getpass("Garmin Connect password: ")

    print("\nLogging in to Garmin Connect...")

    garmin = Garmin(email=email, password=password, prompt_mfa=get_mfa)

    try:
        garmin.login(tokenstore=TOKEN_DIR)
        print("✓ Login successful!")
    except Exception as e:
        print(f"\n✗ Login failed: {e}")
        print("\nTips:")
        print("  - Check your email/password")
        print("  - If you have 2FA, make sure you enter the code when prompted")
        print("  - Garmin sometimes rate-limits logins — wait a minute and try again")
        return

    # Save config (email only — password is NOT stored)
    config["email"] = email
    config["token_dir"] = TOKEN_DIR
    save_config(config)

    # Quick test: fetch last activity
    try:
        last = garmin.get_last_activity()
        if last:
            name = last.get("activityName", "Unknown")
            date = last.get("startTimeLocal", "")[:10]
            print(f"\n✓ Test fetch OK — last activity: \"{name}\" on {date}")
        else:
            print("\n✓ Connected, but no activities found yet.")
    except Exception as e:
        print(f"\n⚠ Connected, but test fetch failed: {e}")

    print(f"\n✓ Config saved to {CONFIG_FILE}")
    print(f"✓ Tokens saved to {TOKEN_DIR}/")
    print(f"\nNext step: run  python garmin_fetch.py  to download your activities.\n")


if __name__ == "__main__":
    main()
