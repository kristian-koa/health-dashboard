"""
Strava OAuth Setup — run this ONCE to authorize your account.
This will open your browser, ask you to approve access, then save
your tokens to strava_config.json for daily use.

Usage:
    python strava_setup.py
"""

import http.server
import threading
import webbrowser
import urllib.parse
import urllib.request
import json
import os

CLIENT_ID     = "222336"
CLIENT_SECRET = "9247f8c18bf2b94d9a010a628c13bb5c9e7456a4"
REDIRECT_URI  = "http://localhost:8080/callback"
SCOPE         = "activity:read_all,read_all"
CONFIG_FILE   = "strava_config.json"

auth_code = None

class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#1a1a2e;color:#fff">
                <h2 style="color:#fc4c02">&#10003; Authorization successful!</h2>
                <p>You can close this tab and return to your terminal.</p>
                </body></html>
            """)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization failed.")

    def log_message(self, format, *args):
        pass  # silence server logs


def exchange_code_for_tokens(code):
    url = "https://www.strava.com/oauth/token"
    data = urllib.parse.urlencode({
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          code,
        "grant_type":    "authorization_code",
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    print("\n=== Strava Running Dashboard — First-Time Setup ===\n")

    # Start callback server
    server = http.server.HTTPServer(("localhost", 8080), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    # Open browser to Strava auth page
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={SCOPE}"
    )
    print("Opening your browser to authorize Strava access...")
    print(f"If it doesn't open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for callback
    print("Waiting for authorization...")
    while auth_code is None:
        import time; time.sleep(0.5)

    server.shutdown()
    print("Authorization received! Exchanging for tokens...")

    tokens = exchange_code_for_tokens(auth_code)

    config = {
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "access_token":  tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at":    tokens["expires_at"],
        "athlete_id":    tokens.get("athlete", {}).get("id"),
        "athlete_name":  tokens.get("athlete", {}).get("firstname", "Athlete"),
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n✓ Tokens saved to {CONFIG_FILE}")
    print(f"✓ Welcome, {config['athlete_name']}!")
    print("\nNext steps:")
    print("  1. Run:  python strava_fetch.py   (downloads all your activities)")
    print("  2. Run:  python serve.py           (opens your dashboard at http://localhost:8080)")


if __name__ == "__main__":
    main()
