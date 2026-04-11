"""
Whoop OAuth Setup — run this once to authorize your Whoop account.

Usage:
    python whoop_setup.py

This will open your browser to log in to Whoop. After you authorize,
Whoop redirects back to localhost and the script saves your tokens.
"""

import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whoop_config.json")
AUTH_URL     = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL    = "https://api.prod.whoop.com/oauth/oauth2/token"

SCOPES = "read:profile read:body_measurement read:recovery read:sleep read:cycles read:workout offline"


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


class CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth redirect from Whoop."""
    auth_code = None

    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if "code" in params:
            CallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#1a1a2e;color:#fff">
                <h1>Whoop Connected!</h1>
                <p>You can close this tab and return to the terminal.</p>
                </body></html>
            """)
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h1>Error: {error}</h1></body></html>".encode())

    def log_message(self, *args):
        pass  # silent


def exchange_code_for_tokens(config, code):
    """Exchange authorization code for access + refresh tokens."""
    data = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  config["redirect_uri"],
        "client_id":     config["client_id"],
        "client_secret": config["client_secret"],
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                 headers={
                                     "Content-Type": "application/x-www-form-urlencoded",
                                     "Accept":       "application/json",
                                     "User-Agent":   "Mozilla/5.0 (RunningStats/1.0)",
                                 })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"\nToken exchange failed: HTTP {e.code}")
        print(f"Response body: {body}\n")
        raise


def main():
    print("\n=== Whoop OAuth Setup ===\n")

    config = load_config()

    # Build authorization URL
    state = secrets.token_urlsafe(32)
    auth_params = urllib.parse.urlencode({
        "client_id":     config["client_id"],
        "redirect_uri":  config["redirect_uri"],
        "response_type": "code",
        "scope":         SCOPES,
        "state":         state,
    })
    auth_url = f"{AUTH_URL}?{auth_params}"

    # Parse port from redirect_uri
    parsed = urllib.parse.urlparse(config["redirect_uri"])
    port = parsed.port or 8080
    callback_path = parsed.path

    # Start temporary callback server
    server = HTTPServer(("127.0.0.1", port), CallbackHandler)

    print(f"Opening browser for Whoop authorization...")
    print(f"If it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for callback
    print("Waiting for authorization...")
    while CallbackHandler.auth_code is None:
        server.handle_request()

    code = CallbackHandler.auth_code
    server.server_close()
    print(f"Got authorization code.")

    # Exchange for tokens
    print("Exchanging code for tokens...")
    tokens = exchange_code_for_tokens(config, code)

    import time
    config["access_token"]  = tokens["access_token"]
    config["refresh_token"] = tokens.get("refresh_token")
    config["expires_at"]    = int(time.time()) + tokens.get("expires_in", 3600)
    save_config(config)

    print(f"\nWhoop connected successfully!")
    print(f"Tokens saved to {CONFIG_FILE}")
    print(f"\nNext: run  python whoop_fetch.py  to download your data.\n")


if __name__ == "__main__":
    main()
