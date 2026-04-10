"""
Running Dashboard Server — serves your dashboard at http://localhost:8080

Also handles the Whoop OAuth callback so you don't need to stop/start servers.

Usage:
    python serve.py

Leave this running in the background while you browse the dashboard.
Press Ctrl+C to stop.
"""

import base64
import http.server
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
import webbrowser
import threading

PORT = 8080
FOLDER = os.path.dirname(os.path.abspath(__file__))

# Files that the frontend is allowed to write to via PUT
WRITABLE_FILES = {"strength_workouts.json", "whoop_data.json"}

# Whoop OAuth settings
WHOOP_AUTH_URL   = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL  = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_CONFIG_FILE = os.path.join(FOLDER, "whoop_config.json")
WHOOP_SCOPES = "read:profile read:body_measurement read:recovery read:sleep read:cycles read:workout offline"


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FOLDER, **kwargs)

    def do_GET(self):
        """Handle GET requests — intercept Whoop auth/callback, serve files otherwise."""
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/whoop_auth":
            self.handle_whoop_auth()
            return

        if parsed.path == "/whoop_callback":
            self.handle_whoop_callback(parsed.query)
            return

        # Default: serve static files
        super().do_GET()

    def handle_whoop_auth(self):
        """Redirect user to Whoop authorization page."""
        try:
            config = load_whoop_config()
            state = secrets.token_urlsafe(32)
            auth_params = urllib.parse.urlencode({
                "client_id":     config["client_id"],
                "redirect_uri":  config["redirect_uri"],
                "response_type": "code",
                "scope":         WHOOP_SCOPES,
                "state":         state,
            })
            self.send_response(302)
            self.send_header("Location", f"{WHOOP_AUTH_URL}?{auth_params}")
            self.end_headers()
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h1>Error: {e}</h1></body></html>".encode())

    def handle_whoop_callback(self, query_string):
        """Handle the Whoop OAuth redirect and exchange code for tokens."""
        params = urllib.parse.parse_qs(query_string)

        if "error" in params:
            error = params.get("error", ["unknown"])[0]
            desc = params.get("error_description", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"""
                <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f0f13;color:#ff5c6a">
                <h1>Whoop Authorization Failed</h1>
                <p>{error}: {desc}</p>
                <p style="color:#8888a0;margin-top:20px">Check your Whoop developer settings and try again.</p>
                </body></html>
            """.encode())
            return

        code = params.get("code", [None])[0]
        if not code:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>No authorization code received</h1></body></html>")
            return

        # Exchange code for tokens
        try:
            config = load_whoop_config()

            token_data = urllib.parse.urlencode({
                "grant_type":    "authorization_code",
                "code":          code,
                "client_id":     config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri":  config["redirect_uri"],
            }).encode()

            req = urllib.request.Request(WHOOP_TOKEN_URL, data=token_data, method="POST",
                                         headers={"User-Agent": "WhoopDashboard/1.0"})
            try:
                with urllib.request.urlopen(req) as resp:
                    tokens = json.loads(resp.read())
            except urllib.error.HTTPError as http_err:
                error_body = http_err.read().decode()
                print(f"Whoop token error: {http_err.code} - {error_body}")
                raise Exception(f"HTTP {http_err.code}: {error_body}")

            config["access_token"]  = tokens["access_token"]
            config["refresh_token"] = tokens.get("refresh_token")
            config["expires_at"]    = int(time.time()) + tokens.get("expires_in", 3600)
            save_whoop_config(config)

            print(f"\n✓ Whoop connected! Tokens saved to whoop_config.json")
            print(f"  Now run:  python whoop_fetch.py\n")

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f0f13;color:#f0f0f5">
                <div style="background:#1a1a24;border:1px solid #2a2a3a;border-radius:16px;padding:40px;max-width:500px;margin:0 auto">
                <h1 style="color:#2dd4a0;font-size:28px">Whoop Connected!</h1>
                <p style="color:#8888a0;margin-top:16px;font-size:16px">Your tokens have been saved.</p>
                <p style="color:#8888a0;margin-top:8px">Next step: run <code style="color:#2dd4a0">python whoop_fetch.py</code> to download your data.</p>
                <p style="margin-top:24px"><a href="/whoop.html" style="color:#4a9eff;text-decoration:none;font-size:16px">Go to Whoop Dashboard &rarr;</a></p>
                </div>
                </body></html>
            """)

        except Exception as e:
            print(f"\n✗ Whoop token exchange failed: {e}\n")
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"""
                <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f0f13;color:#ff5c6a">
                <h1>Token Exchange Failed</h1>
                <p style="color:#8888a0">{str(e)}</p>
                </body></html>
            """.encode())

    def do_PUT(self):
        """Handle PUT requests for saving exercise data."""
        path = self.path.lstrip("/").split("?")[0]
        if path not in WRITABLE_FILES:
            self.send_error(403, "Forbidden")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # Validate JSON
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        filepath = os.path.join(FOLDER, path)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format, *args):
        # Only log errors, not every request
        if args[1] not in ('200', '304'):
            super().log_message(format, *args)


def load_whoop_config():
    with open(WHOOP_CONFIG_FILE) as f:
        return json.load(f)


def save_whoop_config(config):
    with open(WHOOP_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def open_browser():
    import time; time.sleep(0.8)
    webbrowser.open(f"http://localhost:{PORT}/dashboard.html")


if __name__ == "__main__":
    print(f"\n=== Health Dashboard Server ===")
    print(f"Serving from: {FOLDER}")
    print(f"Running:      http://localhost:{PORT}/dashboard.html")
    print(f"Strength:     http://localhost:{PORT}/strength.html")
    print(f"Whoop:        http://localhost:{PORT}/whoop.html")
    print(f"Press Ctrl+C to stop.\n")

    threading.Thread(target=open_browser, daemon=True).start()

    with http.server.HTTPServer(("", PORT), DashboardHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
