#!/usr/bin/env python3
"""Send the rendered Oil Hourly Brief exactly as rendered, over HTTPS (Brevo API, or the Gmail API).

Usage: python3 send_email.py /tmp/email.html "Subject line" [/tmp/email.txt]

Everything private comes from environment variables set in the cloud environment, never this repo:
  SENDER_EMAIL      sending address (must be a verified sender in Brevo)
  OIL_RECIPIENTS    comma-separated recipient addresses
  BREVO_API_KEY     Brevo API key (v3, "API keys" tab, not an SMTP key)
or, instead of BREVO_API_KEY, the Gmail API trio:
  GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN (from get_gmail_token.py)
Exit code 0 = sent. Prints no secrets.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

SENDER_NAME = "Oil Hourly Brief"


def env(name, required=True):
    value = os.environ.get(name, "").strip()
    if required and not value:
        sys.exit(f"missing environment variable: {name}")
    return value


def post(url, payload, headers):
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"send failed: HTTP {e.code} {e.read().decode(errors='replace')[:300]}")


def send_brevo(sender, recipients, subject, html, text):
    payload = {"sender": {"name": SENDER_NAME, "email": sender},
               "to": [{"email": r} for r in recipients],
               "subject": subject, "htmlContent": html, "textContent": text}
    return post("https://api.brevo.com/v3/smtp/email", json.dumps(payload).encode(),
                {"api-key": env("BREVO_API_KEY"), "Content-Type": "application/json", "Accept": "application/json"})


def send_gmail(sender, recipients, subject, html, text):
    token = post("https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "client_id": env("GMAIL_CLIENT_ID"), "client_secret": env("GMAIL_CLIENT_SECRET"),
        "refresh_token": env("GMAIL_REFRESH_TOKEN"), "grant_type": "refresh_token"}).encode(), {})["access_token"]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"{SENDER_NAME} <{sender}>", ", ".join(recipients)
    msg["Date"], msg["Message-ID"] = formatdate(localtime=False), make_msgid(domain=sender.split("@")[-1])
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json.dumps({"raw": raw}).encode(),
                {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})


def main():
    html_path, subject = sys.argv[1], sys.argv[2]
    text_path = sys.argv[3] if len(sys.argv) > 3 else None
    sender = env("SENDER_EMAIL", required=False) or env("GMAIL_USER")
    recipients = [r.strip() for r in env("OIL_RECIPIENTS").split(",") if r.strip()]
    html = open(html_path, encoding="utf-8").read()
    text = open(text_path, encoding="utf-8").read() if text_path else "Oil Hourly Brief: open in an HTML-capable mail app."
    if env("BREVO_API_KEY", required=False):
        result, via = send_brevo(sender, recipients, subject, html, text), "Brevo"
    else:
        result, via = send_gmail(sender, recipients, subject, html, text), "Gmail API"
    print(f"sent via {via} to {len(recipients)} recipients (id {result.get('messageId') or result.get('id')})")


if __name__ == "__main__":
    main()
