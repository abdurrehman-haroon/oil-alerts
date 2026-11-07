#!/usr/bin/env python3
"""One-time helper, run on your own computer: get a Gmail refresh token for send_email.py.

Usage: python3 get_gmail_token.py ~/Downloads/client_secret_XXXX.json

1. Opens Google's consent page in your browser (sign in as the sending Gmail account).
2. Google redirects back to a temporary local page; this script catches the code.
3. Prints GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN lines to paste into the
   cloud environment's variables. Nothing is saved to disk or sent anywhere except Google.
Only the gmail.send permission is requested: the token can send mail but cannot read it.
"""
import http.server
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/gmail.send"


def main():
    client = json.load(open(sys.argv[1]))
    client = client.get("installed") or client.get("web")
    cid, csecret = client["client_id"], client["client_secret"]
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state and "code" in q:
                result["code"] = q["code"][0]
                msg = "Done. You can close this tab and go back to the terminal."
            else:
                msg = "Something went wrong: " + q.get("error", ["unknown"])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state})
    print("Opening your browser for Google sign-in. If it doesn't open, visit:\n" + url + "\n")
    webbrowser.open(url)
    while "code" not in result:
        server.handle_request()

    body = urllib.parse.urlencode({"code": result["code"], "client_id": cid, "client_secret": csecret,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    tokens = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body, timeout=30))
    if "refresh_token" not in tokens:
        sys.exit("Google returned no refresh token. Remove the app's access at myaccount.google.com/permissions and run again.")
    print("Paste these three lines into the cloud environment's variables:\n")
    print(f"GMAIL_CLIENT_ID={cid}")
    print(f"GMAIL_CLIENT_SECRET={csecret}")
    print(f"GMAIL_REFRESH_TOKEN={tokens['refresh_token']}")


if __name__ == "__main__":
    main()
