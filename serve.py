"""
Running Dashboard Server — serves your dashboard at http://localhost:8080

Also handles the Whoop OAuth callback so you don't need to stop/start servers.

Usage:
    python serve.py

Leave this running in the background while you browse the dashboard.
Press Ctrl+C to stop.
"""

import base64
import html as html_mod
import http.server
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
import webbrowser
import threading
import traceback

PORT = 8080
FOLDER = os.path.dirname(os.path.abspath(__file__))

# Files that the frontend is allowed to write to via PUT
WRITABLE_FILES = {"strength_workouts.json", "whoop_data.json"}

# Garmin settings
GARMIN_CONFIG_FILE = os.path.join(FOLDER, "garmin_config.json")
GARMIN_TOKEN_DIR   = os.path.join(FOLDER, ".garmin_tokens")

# Whoop OAuth settings
WHOOP_AUTH_URL   = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL  = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_CONFIG_FILE = os.path.join(FOLDER, "whoop_config.json")
WHOOP_SCOPES = "read:profile read:body_measurement read:recovery read:sleep read:cycles read:workout offline"


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FOLDER, **kwargs)

    def do_GET(self):
        """Handle GET requests — intercept auth routes, serve files otherwise."""
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/whoop_auth":
            self.handle_whoop_auth()
            return

        if parsed.path == "/whoop_callback":
            self.handle_whoop_callback(parsed.query)
            return

        if parsed.path == "/garmin_setup":
            self.serve_garmin_setup_page()
            return

        # Default: serve static files
        super().do_GET()

    def do_POST(self):
        """Handle POST requests — Garmin login."""
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/garmin_login":
            self.handle_garmin_login()
            return

        self.send_error(404, "Not Found")

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

    def serve_garmin_setup_page(self, error_msg=None, success=False):
        """Serve the Garmin Connect login form."""
        parts = [
            '<!DOCTYPE html>',
            '<html><head><meta charset="UTF-8"><title>Garmin Connect Setup</title></head>',
            '<body style="font-family:Segoe UI,system-ui,sans-serif;background:#0f0f13;color:#f0f0f5;'
            'display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0">',
            '<div style="background:#1a1a24;border:1px solid #2a2a3a;border-radius:16px;padding:40px;'
            'max-width:440px;width:100%">',
            '<div style="text-align:center;margin-bottom:24px">',
            '<div style="width:48px;height:48px;background:#4a9eff;border-radius:12px;'
            'display:inline-flex;align-items:center;justify-content:center;font-size:24px;'
            'margin-bottom:12px">&#9201;</div>',
            '<h1 style="font-size:22px;margin:0">Connect Garmin</h1>',
            '<p style="color:#8888a0;font-size:13px;margin-top:6px">Sign in with your Garmin Connect credentials</p>',
            '</div>',
        ]

        if error_msg:
            safe = html_mod.escape(error_msg)
            parts.append(
                '<div style="background:#ff5c6a22;border:1px solid #ff5c6a44;border-radius:8px;'
                'padding:12px 16px;margin-bottom:20px;color:#ff5c6a;font-size:13px">'
                + safe + '</div>'
            )

        if success:
            parts.append(
                '<div style="background:#2dd4a022;border:1px solid #2dd4a044;border-radius:8px;'
                'padding:12px 16px;margin-bottom:20px;color:#2dd4a0;font-size:13px">'
                'Connected! Your tokens have been saved.</div>'
            )

        if not success:
            parts.append("""
<form method="POST" action="/garmin_login" id="loginForm">
  <div style="margin-bottom:16px">
    <label style="display:block;color:#8888a0;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Email</label>
    <input name="email" type="email" required
      style="width:100%;padding:10px 14px;background:#22222f;border:1px solid #2a2a3a;border-radius:8px;color:#f0f0f5;font-size:14px;outline:none;box-sizing:border-box"
      placeholder="your@email.com">
  </div>
  <div style="margin-bottom:16px">
    <label style="display:block;color:#8888a0;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Password</label>
    <input name="password" type="password" required
      style="width:100%;padding:10px 14px;background:#22222f;border:1px solid #2a2a3a;border-radius:8px;color:#f0f0f5;font-size:14px;outline:none;box-sizing:border-box"
      placeholder="Your Garmin password">
  </div>
  <button type="submit" id="submitBtn"
    style="width:100%;padding:12px;background:#4a9eff;border:none;border-radius:8px;color:#fff;font-size:15px;font-weight:600;cursor:pointer;transition:background 0.15s">
    Sign In
  </button>
</form>
<script>
  document.getElementById("loginForm").addEventListener("submit", function() {
    var btn = document.getElementById("submitBtn");
    btn.textContent = "Connecting to Garmin... (this may take a moment)";
    btn.style.background = "#3a3a4a";
    btn.style.cursor = "wait";
    btn.disabled = true;
  });
</script>
""")

        parts.append(
            '<p style="color:#8888a0;font-size:11px;margin-top:20px;text-align:center;line-height:1.5">'
            'Your password is sent only to Garmin servers and is <strong>not stored</strong> locally.<br>'
            'Only a session token is saved for future data fetches.</p>'
        )

        if success:
            parts.append(
                '<p style="text-align:center;margin-top:16px">'
                '<a href="/garmin.html" style="color:#4a9eff;text-decoration:none;font-size:14px">'
                'Go to Garmin Dashboard &rarr;</a></p>'
            )

        parts.append('</div></body></html>')

        page = "\n".join(parts)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def handle_garmin_login(self):
        """Handle the Garmin login form submission."""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)

        email    = params.get("email", [""])[0].strip()
        password = params.get("password", [""])[0]

        if not email or not password:
            self.serve_garmin_setup_page(error_msg="Please enter both email and password.")
            return

        try:
            from garminconnect import Garmin

            print(f"\n  Garmin login attempt for {email}...")

            # MFA handler — we'll serve a page for this if needed
            mfa_code_holder = {}

            garmin = Garmin(email=email, password=password)

            # Try login with retries and delays
            max_retries = 3
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    print(f"  Attempt {attempt}/{max_retries}...")
                    garmin.login(tokenstore=GARMIN_TOKEN_DIR)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    err_str = str(e).lower()
                    if "429" in err_str or "rate limit" in err_str or "cloudflare" in err_str:
                        if attempt < max_retries:
                            wait = attempt * 10
                            print(f"  Rate limited — waiting {wait}s before retry...")
                            time.sleep(wait)
                            continue
                    # Non-rate-limit error — don't retry
                    break

            if last_error:
                err_msg = str(last_error)
                if "429" in err_msg or "rate limit" in err_msg.lower():
                    err_msg = ("Garmin is rate-limiting login attempts (429). "
                               "Please wait 10-15 minutes and try again. "
                               "This is a Garmin server-side restriction, not a credentials issue.")
                elif "403" in err_msg:
                    err_msg = ("Garmin returned 403 Forbidden. This usually means Cloudflare is blocking the request. "
                               "Try again in a few minutes.")
                print(f"  ✗ Login failed: {last_error}")
                self.serve_garmin_setup_page(error_msg=err_msg)
                return

            # Save config (email only, NOT password)
            config = {"email": email, "token_dir": GARMIN_TOKEN_DIR}
            with open(GARMIN_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)

            # Quick test
            try:
                last = garmin.get_last_activity()
                if last:
                    name = last.get("activityName", "Unknown")
                    print(f"  ✓ Connected! Last activity: {name}")
                else:
                    print(f"  ✓ Connected (no activities found)")
            except Exception:
                print(f"  ✓ Connected (test fetch skipped)")

            print(f"  ✓ Garmin tokens saved to {GARMIN_TOKEN_DIR}/")
            print(f"  Next: run  python garmin_fetch.py\n")

            self.serve_garmin_setup_page(success=True)

        except ImportError:
            self.serve_garmin_setup_page(
                error_msg="The 'garminconnect' Python package is not installed. "
                          "Run: pip install garminconnect")
        except Exception as e:
            traceback.print_exc()
            self.serve_garmin_setup_page(error_msg=f"Unexpected error: {str(e)}")

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
    print(f"Garmin:       http://localhost:{PORT}/garmin.html")
    print(f"Press Ctrl+C to stop.\n")

    threading.Thread(target=open_browser, daemon=True).start()

    with http.server.HTTPServer(("", PORT), DashboardHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
