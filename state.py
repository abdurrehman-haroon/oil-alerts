#!/usr/bin/env python3
"""Keep a record of every email on `main`, so later runs don't repeat stories and the daily wrap has history.

Two append-only files per month, committed to `main` after each send:
  data/stories/YYYY-MM.jsonl     one line per story sent: headline, link, source, sentiment, impact, horizon,
                                 region, why, summary, the CL/Brent prices at send time, and sent_utc
  data/snapshots/YYYY-MM.jsonl   one line per run: CL/Brent prices, funding and Binance positioning

  python3 state.py load                                  # last 48h of sent stories as JSON (empty list if none)
  python3 state.py save /tmp/analysis.json /tmp/data.json  # append this run and push to main

Commits are authored as the repository owner so they count on their GitHub profile. The commit is built on top of
origin/main with git plumbing, so it works whatever branch the checkout is on, and retries if main moved meanwhile.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

BRANCH = "main"
KEEP = dt.timedelta(hours=48)
AUTHOR = {"GIT_AUTHOR_NAME": "abdurrehman-haroon",
          "GIT_AUTHOR_EMAIL": "133659511+abdurrehman-haroon@users.noreply.github.com"}
AUTHOR.update({"GIT_COMMITTER_NAME": AUTHOR["GIT_AUTHOR_NAME"], "GIT_COMMITTER_EMAIL": AUTHOR["GIT_AUTHOR_EMAIL"]})
UTC = dt.timezone.utc


def git(*args, input_text=None, check=True, env=None):
    return subprocess.run(["git", *args], input=input_text, text=True, capture_output=True, check=check,
                          env={**os.environ, **AUTHOR, **(env or {})}).stdout.strip()


def fetch():
    git("fetch", "--quiet", "origin", f"{BRANCH}:refs/remotes/origin/{BRANCH}")


def read_remote(path):
    """Contents of a file on origin/main, or '' if it doesn't exist yet."""
    r = subprocess.run(["git", "show", f"origin/{BRANCH}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def month_path(kind, when):
    return f"data/{kind}/{when:%Y-%m}.jsonl"


def read_lines(path):
    out = []
    for line in read_remote(path).splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def stories_since(cutoff):
    """Sent stories newer than cutoff, oldest first, reading this month and last month's files."""
    now = dt.datetime.now(UTC)
    months = sorted({month_path("stories", now), month_path("stories", now.replace(day=1) - dt.timedelta(days=1)),
                     month_path("stories", cutoff)})
    items = [i for p in months for i in read_lines(p)]
    return [i for i in items if dt.datetime.fromisoformat(i["sent_utc"]) >= cutoff]


def load():
    """Sent stories from the last 48h, newest first. Never raises: no history means nothing sent yet."""
    try:
        fetch()
        items = stories_since(dt.datetime.now(UTC) - KEEP)
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError):
        return []
    return sorted(items, key=lambda i: i["sent_utc"], reverse=True)


def _px(prices, key, side, field="last"):
    try:
        return float(prices[key][side][field])
    except (KeyError, TypeError, ValueError):
        return None


def price_fields(prices):
    return {"cl_tm": _px(prices, "CL", "exchange"), "cl_bn": _px(prices, "CL", "binance"),
            "bz_tm": _px(prices, "BRENT", "exchange"), "bz_bn": _px(prices, "BRENT", "binance")}


def build_lines(analysis, data, now):
    stamp = now.replace(microsecond=0).isoformat()
    prices = (data or {}).get("prices", {})
    px = price_fields(prices)
    keep = ("headline", "link", "source", "sources_count", "headline_only", "sentiment", "impact", "horizon",
            "region", "why", "summary", "published_utc")
    stories = [{**{k: s.get(k) for k in keep}, "sent_utc": stamp, "prices": px} for s in analysis.get("stories", [])]
    snapshot = None
    if data:
        snapshot = {"time_utc": stamp, "prices": px,
                    "market_open": prices.get("CL", {}).get("exchange", {}).get("market_open"),
                    "funding": {"CL": _px(prices, "CL", "binance", "funding_rate"),
                                "BRENT": _px(prices, "BRENT", "binance", "funding_rate")},
                    "positioning": data.get("positioning", {}), "stories": len(stories)}
    return stories, snapshot


def append_blob(path, new_lines):
    text = read_remote(path)
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in new_lines)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write(text)
    return git("hash-object", "-w", f.name)


def commit_and_push(stories, snapshot, now, attempts=4):
    msg = f"data: {len(stories)} stories at {now:%Y-%m-%d %H:%M} UTC"
    for attempt in range(attempts):
        fetch()
        with tempfile.TemporaryDirectory() as tmp:
            idx = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
            git("read-tree", f"origin/{BRANCH}", env=idx)
            changes = []
            if stories:
                changes.append(month_path("stories", now))
            if snapshot:
                changes.append(month_path("snapshots", now))
            for path in changes:
                lines = stories if "/stories/" in path else [snapshot]
                git("update-index", "--add", "--cacheinfo", f"100644,{append_blob(path, lines)},{path}", env=idx)
            tree = git("write-tree", env=idx)
        commit = git("commit-tree", tree, "-p", f"origin/{BRANCH}", "-m", msg)
        r = subprocess.run(["git", "push", "--quiet", "origin", f"{commit}:refs/heads/{BRANCH}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return
        if attempt == attempts - 1:
            raise SystemExit(f"push to {BRANCH} failed: {r.stderr.strip()[-300:]}")


def save(analysis_path, data_path=None):
    now = dt.datetime.now(UTC)
    analysis = json.load(open(analysis_path, encoding="utf-8"))
    data = json.load(open(data_path, encoding="utf-8")) if data_path else None
    stories, snapshot = build_lines(analysis, data, now)
    if not stories and not snapshot:
        print("nothing to save")
        return
    commit_and_push(stories, snapshot, now)
    print(f"saved {len(stories)} stories{' and a snapshot' if snapshot else ''} to {BRANCH}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["load"]:
        print(json.dumps(load(), ensure_ascii=False, indent=1))
    elif sys.argv[1:2] == ["save"] and len(sys.argv) in (3, 4):
        save(*sys.argv[2:])
    else:
        sys.exit(__doc__)
