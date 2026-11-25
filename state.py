#!/usr/bin/env python3
"""Remember which stories were already emailed, so later runs don't repeat them.

The list lives in `sent.json` on the `claude/oil-state` branch of this repository (headlines and public
links only, no personal data). It is read and written through GitHub's REST API over HTTPS, because the
cloud routine's own git checkout is read-only (git push is blocked by the sandbox proxy).

  python3 state.py load                       # print the last 48h of sent stories as JSON
  python3 state.py save /tmp/analysis.json    # add this run's stories to sent.json

Reading works without a token (public repo). Saving needs GH_STATE_TOKEN: a fine-grained personal access
token limited to this repository with "Contents: Read and write".
"""
import base64
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

REPO = "abdurrehman-haroon/oil-alerts"
BRANCH = "claude/oil-state"
PATH = "sent.json"
KEEP = dt.timedelta(hours=48)
API = f"https://api.github.com/repos/{REPO}"


def _call(method, url, body=None, token=None):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "oil-alerts-state"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _read(token=None):
    """(items, sha) from sent.json on the state branch; ([], None) if the file or branch doesn't exist yet."""
    try:
        f = _call("GET", f"{API}/contents/{PATH}?ref={BRANCH}", token=token)
        return json.loads(base64.b64decode(f["content"])), f["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [], None
        raise


def _recent(items):
    cutoff = dt.datetime.now(dt.timezone.utc) - KEEP
    return [i for i in items if dt.datetime.fromisoformat(i["sent_utc"]) >= cutoff]


def load():
    """Sent stories from the last 48h, newest first. Never raises."""
    try:
        return _recent(_read(os.environ.get("GH_STATE_TOKEN"))[0])
    except Exception as e:  # noqa: BLE001 — memory is a nice-to-have; never block the email
        print(f"state: could not read {PATH} ({type(e).__name__}: {e})", file=sys.stderr)
        return []


def _ensure_branch(token):
    try:
        _call("GET", f"{API}/git/ref/heads/{BRANCH}", token=token)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        main_sha = _call("GET", f"{API}/git/ref/heads/main", token=token)["object"]["sha"]
        _call("POST", f"{API}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": main_sha}, token=token)


def save(analysis_path):
    token = os.environ.get("GH_STATE_TOKEN", "").strip()
    if not token:
        sys.exit("state: GH_STATE_TOKEN is not set, so sent stories were not recorded")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    stories = json.load(open(analysis_path)).get("stories", [])
    _ensure_branch(token)
    items, sha = _read(token)
    items = [{"headline": s["headline"], "link": s["link"], "sentiment": s.get("sentiment"),
              "impact": s.get("impact"), "sent_utc": now} for s in stories] + _recent(items)
    body = {"message": f"Sent {len(stories)} stories at {now}", "branch": BRANCH,
            "content": base64.b64encode(json.dumps(items, ensure_ascii=False, indent=1).encode()).decode(),
            "committer": {"name": "oil-alerts bot", "email": "oil-alerts-bot@users.noreply.github.com"}}
    if sha:
        body["sha"] = sha
    _call("PUT", f"{API}/contents/{PATH}", body, token=token)
    print(f"saved {len(stories)} stories ({len(items)} remembered from the last 48h)")


if __name__ == "__main__":
    if sys.argv[1:2] == ["load"]:
        print(json.dumps(load(), ensure_ascii=False, indent=1))
    elif sys.argv[1:2] == ["save"] and len(sys.argv) == 3:
        save(sys.argv[2])
    else:
        sys.exit(__doc__)
