#!/usr/bin/env python3
"""Keep a record of every run on `main`: no repeated stories, history for the Daily Wrap, and later analysis.

Append-only JSON Lines files, one per month, committed to `main` after each send:
  data/stories/YYYY-MM.jsonl     every story emailed: metrics, text, publish/send time, CL/Brent prices at send
  data/news/YYYY-MM.jsonl        every news item fetched, with status: sent, already_sent, or why it was dropped
  data/snapshots/YYYY-MM.jsonl   one line per run: prices, 1h/24h context, funding, positioning, calendar, run health
  data/outcomes/YYYY-MM.jsonl    CL 1h/4h/24h after each story and whether its sentiment call held (scored 24h later)
  data/daily/YYYY-MM.jsonl       one line per Daily Wrap: day OHLC + settle, positioning, sentiment tally, top stories

  python3 state.py load                                    # last 48h of sent stories as JSON (empty list if none)
  python3 state.py save /tmp/analysis.json /tmp/data.json  # brief: append this run and push to main
  python3 state.py save-wrap /tmp/wrap.json                # wrap: append the day's row and push to main

Commits are authored as the repository owner so they count on their GitHub profile. Each commit is built on top of
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
    """This run's lines: stories sent, every news item fetched (kept or why dropped), and a snapshot."""
    stamp = now.replace(microsecond=0).isoformat()
    prices = (data or {}).get("prices", {})
    px = price_fields(prices)
    keep = ("headline", "link", "source", "sources_count", "headline_only", "sentiment", "impact", "horizon",
            "region", "why", "summary", "published_utc")
    stories = [{**{k: s.get(k) for k in keep}, "sent_utc": stamp, "prices": px} for s in analysis.get("stories", [])]
    snapshot, news = None, []
    if data:
        kept = {s.get("link") for s in analysis.get("stories", [])}
        why = {d.get("link"): d.get("reason") for d in analysis.get("dropped", []) if d.get("link")}
        for n in data.get("news", []):
            status = "sent" if n.get("link") in kept else why.get(n.get("link")) or (
                "already_sent" if n.get("already_sent") else "dropped")
            news.append({"run_utc": stamp, "source": n.get("source"), "access": n.get("access"),
                         "title": n.get("title"), "link": n.get("link"), "published_utc": n.get("published_utc"),
                         "summary": (n.get("summary") or "")[:300], "status": status})
        ex = {k: prices.get(k, {}).get("exchange", {}) for k in ("CL", "BRENT")}
        bn = {k: prices.get(k, {}).get("binance", {}) for k in ("CL", "BRENT")}
        num = lambda x: None if x in (None, "") else float(x)
        generated = data.get("generated_utc")
        snapshot = {"time_utc": stamp, "prices": px,
                    "market_open": ex["CL"].get("market_open"),
                    "context": {"cl_tm_change_1h": num(ex["CL"].get("change_1h")), "cl_bn_change_1h": num(bn["CL"].get("change_1h")),
                                "bz_tm_change_1h": num(ex["BRENT"].get("change_1h")), "bz_bn_change_1h": num(bn["BRENT"].get("change_1h")),
                                "cl_prev_day": num(ex["CL"].get("prev_day")), "bz_prev_day": num(ex["BRENT"].get("prev_day")),
                                "cl_bn_change_pct_24h": num(bn["CL"].get("change_pct_24h")),
                                "bz_bn_change_pct_24h": num(bn["BRENT"].get("change_pct_24h"))},
                    "funding": {"CL": _px(prices, "CL", "binance", "funding_rate"),
                                "BRENT": _px(prices, "BRENT", "binance", "funding_rate")},
                    "positioning": data.get("positioning", {}),
                    "calendar": [{k: e.get(k) for k in ("time_utc", "country", "title", "impact", "forecast", "previous")}
                                 for e in data.get("calendar_next_24h", [])],
                    "stories": len(stories),
                    "health": {"errors": data.get("errors", []), "sources_ok": data.get("sources_ok", []),
                               "news_fetched": len(data.get("news", [])),
                               "run_seconds": round((now - dt.datetime.fromisoformat(generated)).total_seconds())
                               if generated else None}}
    return stories, snapshot, news


# ---------------------------------------------------------------- did the call come true?
LEAN = {"Bullish": 1, "Slightly Bullish": 1, "Neutral": 0, "Slightly Bearish": -1, "Bearish": -1}
HORIZONS = (("1h", dt.timedelta(hours=1)), ("4h", dt.timedelta(hours=4)), ("24h", dt.timedelta(hours=24)))


def cl_candles(start, end):
    """Traditional-market CL (Hyperliquid oracle) 15-minute closes as [(open_time, close)]."""
    import fetch_data as fd  # same folder
    bars = fd.post_json("https://api.hyperliquid.xyz/info", {"type": "candleSnapshot", "req": {
        "coin": "xyz:CL", "interval": "15m", "startTime": int(start.timestamp() * 1000), "endTime": int(end.timestamp() * 1000)}})
    return [(dt.datetime.fromtimestamp(b["t"] / 1000, UTC), float(b["c"])) for b in bars]


def outcomes(now):
    """For stories sent 24–72h ago and not scored yet: CL 1h, 4h and 24h after the email, and whether the call held."""
    start = now - dt.timedelta(hours=72)
    due = [s for s in stories_since(start) if dt.datetime.fromisoformat(s["sent_utc"]) <= now - dt.timedelta(hours=24)]
    if not due:
        return []
    months = sorted({month_path("outcomes", start), month_path("outcomes", now)})
    done = {(o["link"], o["sent_utc"]) for p in months for o in read_lines(p)}
    due = [s for s in due if (s["link"], s["sent_utc"]) not in done]
    if not due:
        return []
    bars = cl_candles(start - dt.timedelta(hours=1), now)

    def at(t):
        hit = [c for o, c in bars if o + dt.timedelta(minutes=15) <= t]  # last close at or before t
        return hit[-1] if hit else None

    out = []
    for s in due:
        t0 = dt.datetime.fromisoformat(s["sent_utc"])
        p0 = (s.get("prices") or {}).get("cl_tm") or at(t0)
        row = {"link": s["link"], "headline": s["headline"], "sent_utc": s["sent_utc"], "sentiment": s.get("sentiment"),
               "impact": s.get("impact"), "cl_at_send": p0}
        for name, delta in HORIZONS:
            p = at(t0 + delta)
            move = round(p - p0, 3) if (p is not None and p0) else None
            row[f"cl_{name}"], row[f"move_{name}"] = p, move
            row[f"move_pct_{name}"] = round(move / p0 * 100, 2) if move is not None else None
            lean = LEAN.get(s.get("sentiment"))
            row[f"call_{name}"] = (None if move is None or not lean else
                                   "flat" if abs(move) < 0.05 else "right" if (move > 0) == (lean > 0) else "wrong")
        out.append(row)
    return out


# ---------------------------------------------------------------- commit
def append_blob(path, new_lines):
    text = read_remote(path)
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in new_lines)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write(text)
    return git("hash-object", "-w", f.name)


def commit_and_push(files, msg, attempts=4):
    """files: {path: [lines to append]}. One commit on top of origin/main; retried if main moved meanwhile."""
    files = {p: lines for p, lines in files.items() if lines}
    if not files:
        return False
    for attempt in range(attempts):
        fetch()
        with tempfile.TemporaryDirectory() as tmp:
            idx = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
            git("read-tree", f"origin/{BRANCH}", env=idx)
            for path, lines in files.items():
                git("update-index", "--add", "--cacheinfo", f"100644,{append_blob(path, lines)},{path}", env=idx)
            tree = git("write-tree", env=idx)
        commit = git("commit-tree", tree, "-p", f"origin/{BRANCH}", "-m", msg)
        r = subprocess.run(["git", "push", "--quiet", "origin", f"{commit}:refs/heads/{BRANCH}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return True
        if attempt == attempts - 1:
            raise SystemExit(f"push to {BRANCH} failed: {r.stderr.strip()[-300:]}")


def save(analysis_path, data_path=None):
    now = dt.datetime.now(UTC)
    analysis = json.load(open(analysis_path, encoding="utf-8"))
    data = json.load(open(data_path, encoding="utf-8")) if data_path else None
    stories, snapshot, news = build_lines(analysis, data, now)
    try:
        scored = outcomes(now)
    except Exception as e:  # noqa: BLE001  (scoring must never block saving the run)
        scored = []
        print(f"outcomes skipped: {e}")
    commit_and_push({month_path("stories", now): stories, month_path("snapshots", now): [snapshot] if snapshot else [],
                     month_path("news", now): news, month_path("outcomes", now): scored},
                    f"data: {len(stories)} stories at {now:%Y-%m-%d %H:%M} UTC")
    print(f"saved {len(stories)} stories, {len(news)} news items, {len(scored)} scored outcomes"
          f"{' and a snapshot' if snapshot else ''} to {BRANCH}")


# ---------------------------------------------------------------- daily wrap row
SETTLE_UTC = (19, 30)  # NYMEX 2:30 PM New York; 18:30 UTC under US daylight saving


def save_wrap(wrap_path):
    w = json.load(open(wrap_path, encoding="utf-8"))
    now = dt.datetime.fromisoformat(w["generated_utc"])
    settle = now.replace(hour=SETTLE_UTC[0], minute=SETTLE_UTC[1], second=0, microsecond=0)
    if settle > now:
        settle -= dt.timedelta(days=1)

    def settle_px(series):
        hit = [p["c"] for p in series or [] if dt.datetime.fromisoformat(p["t"]) <= settle]
        return hit[-1] if hit else None

    prices = {}
    for k, v in w.get("prices", {}).items():
        for side, x in (v or {}).items():
            if x:
                prices[f"{k}_{side}"] = {f: x.get(f) for f in ("open", "high", "low", "close", "change", "change_pct")}
                prices[f"{k}_{side}"]["settle"] = settle_px(x.get("series"))
    row = {"date_utc": now.date().isoformat(), "generated_utc": w["generated_utc"], "window_start_utc": w.get("window_start_utc"),
           "prices": prices, "settle_utc": settle.isoformat(), "positioning": w.get("positioning", {}),
           "funding": {k: _px(w.get("live", {}), k, "binance", "funding_rate") for k in ("CL", "BRENT")},
           "story_count": w.get("story_count"), "sentiment_tally": w.get("sentiment_tally"),
           "top_stories": [{k: s.get(k) for k in ("headline", "link", "source", "sentiment", "impact", "sent_utc")}
                           for s in w.get("top_stories", [])],
           "errors": w.get("errors", [])}
    commit_and_push({month_path("daily", now): [row]}, f"data: daily wrap {now:%Y-%m-%d}")
    print(f"saved daily row for {row['date_utc']} to {BRANCH}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["load"]:
        print(json.dumps(load(), ensure_ascii=False, indent=1))
    elif sys.argv[1:2] == ["save"] and len(sys.argv) in (3, 4):
        save(*sys.argv[2:])
    elif sys.argv[1:2] == ["save-wrap"] and len(sys.argv) == 3:
        save_wrap(sys.argv[2])
    else:
        sys.exit(__doc__)
