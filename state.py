#!/usr/bin/env python3
"""Remember which stories were already emailed, so later runs don't repeat them.

The list lives in `sent.json` on the `claude/oil-state` branch of this repository (headlines and public
links only, no personal data), kept apart from `main` so the code history stays clean.

  python3 state.py load                 # print the last 48h of sent stories as JSON (empty list if none)
  python3 state.py save /tmp/analysis.json   # add this run's stories and push the branch
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

BRANCH = "claude/oil-state"
KEEP = dt.timedelta(hours=48)
BOT = {"GIT_AUTHOR_NAME": "oil-alerts bot", "GIT_AUTHOR_EMAIL": "oil-alerts-bot@users.noreply.github.com",
       "GIT_COMMITTER_NAME": "oil-alerts bot", "GIT_COMMITTER_EMAIL": "oil-alerts-bot@users.noreply.github.com"}


def git(*args, input_text=None, check=True):
    return subprocess.run(["git", *args], input=input_text, text=True, capture_output=True, check=check,
                          env={**os.environ, **BOT}).stdout.strip()


def load():
    """Sent stories from the last 48h, newest first. Never raises: a missing branch means nothing sent yet."""
    try:
        git("fetch", "--quiet", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}")
        items = json.loads(git("show", f"origin/{BRANCH}:sent.json"))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []
    cutoff = dt.datetime.now(dt.timezone.utc) - KEEP
    return [i for i in items if dt.datetime.fromisoformat(i["sent_utc"]) >= cutoff]


def save(analysis_path):
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    stories = json.load(open(analysis_path)).get("stories", [])
    items = [{"headline": s["headline"], "link": s["link"], "sentiment": s.get("sentiment"),
              "impact": s.get("impact"), "sent_utc": now} for s in stories] + load()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    blob = git("hash-object", "-w", f.name)
    tree = git("mktree", input_text=f"100644 blob {blob}\tsent.json\n")
    has_parent = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{BRANCH}"],
                                capture_output=True).returncode == 0
    parent = ["-p", f"origin/{BRANCH}"] if has_parent else []
    commit = git("commit-tree", tree, *parent, "-m", f"Sent {len(stories)} stories at {now}")
    git("push", "--quiet", "origin", f"{commit}:refs/heads/{BRANCH}")
    print(f"saved {len(stories)} stories ({len(items)} remembered from the last 48h)")


if __name__ == "__main__":
    if sys.argv[1:2] == ["load"]:
        print(json.dumps(load(), ensure_ascii=False, indent=1))
    elif sys.argv[1:2] == ["save"] and len(sys.argv) == 3:
        save(sys.argv[2])
    else:
        sys.exit(__doc__)
