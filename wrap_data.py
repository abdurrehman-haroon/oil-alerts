#!/usr/bin/env python3
"""Collect everything the Daily Wrap needs (the last 24 hours) and print one JSON document.

  python3 wrap_data.py > /tmp/wrap.json

- prices: CL and Brent open/high/low/close and change over the day, plus a 15-minute series for the chart,
  from Hyperliquid (traditional market) and Binance
- positioning: Binance crowd, open interest and taker flow now, with their 24h changes, plus the per-run
  snapshots the briefs saved during the day
- stories: every story the briefs sent in the window, with its metrics, the price when it was sent and how far
  CL has moved since; a sentiment and impact tally
"""
import datetime as dt
import json
import sys

import fetch_data as fd
import state

UTC = dt.timezone.utc
PKT = dt.timezone(dt.timedelta(hours=5))
WINDOW = dt.timedelta(hours=24)
IMPACT_RANK = {"High": 3, "Medium": 2, "Low": 1}


def ohlc(series):
    """series: [(time_iso, open, high, low, close)] oldest first."""
    if not series:
        return None
    o, c = series[0][1], series[-1][4]
    return {"open": o, "high": max(r[2] for r in series), "low": min(r[3] for r in series), "close": c,
            "change": round(c - o, 2), "change_pct": round((c / o - 1) * 100, 2) if o else None,
            "series": [{"t": r[0], "c": r[4]} for r in series]}


def hyperliquid(coin, start, now):
    bars = fd.post_json("https://api.hyperliquid.xyz/info", {"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "15m", "startTime": int(start.timestamp() * 1000), "endTime": int(now.timestamp() * 1000)}})
    return [(dt.datetime.fromtimestamp(b["t"] / 1000, UTC).isoformat(), float(b["o"]), float(b["h"]), float(b["l"]),
             float(b["c"])) for b in bars]


def binance(sym, start):
    rows = fd.get_json(f"https://www.binance.com/fapi/v1/klines?symbol={sym}&interval=15m"
                       f"&startTime={int(start.timestamp() * 1000)}&limit=100")
    return [(dt.datetime.fromtimestamp(r[0] / 1000, UTC).isoformat(), float(r[1]), float(r[2]), float(r[3]),
             float(r[4])) for r in rows]


def day_prices(start, now):
    out, errors = {}, []
    for key, coin, sym in (("CL", "xyz:CL", "CLUSDT"), ("BRENT", "xyz:BRENTOIL", "BZUSDT")):
        for side, fn in (("exchange", lambda: hyperliquid(coin, start, now)), ("binance", lambda: binance(sym, start))):
            try:
                out.setdefault(key, {})[side] = ohlc(fn())
            except Exception as e:  # noqa: BLE001
                errors.append(f"{side} day prices {key}: {e}")
    return out, errors


def positioning_hourly():
    """Raw hourly Binance rows (last 25h) for the wrap's crowd chart and the per-story 'since then' reads."""
    out, errors = {}, []
    for sym in ("CLUSDT", "BZUSDT"):
        for name in ("globalLongShortAccountRatio", "openInterestHist", "takerlongshortRatio"):
            try:
                out.setdefault(sym, {})[name] = fd.get_json(
                    f"https://www.binance.com/futures/data/{name}?symbol={sym}&period=1h&limit=25")
            except Exception as e:  # noqa: BLE001
                errors.append(f"hourly {name} {sym}: {e}")
    return out, errors


def main():
    now = dt.datetime.now(UTC)
    start = now - WINDOW
    prices, errors = day_prices(start, now)
    pos, e2 = fd.positioning()
    live, e3 = fd.prices()
    hourly, e4 = positioning_hourly()
    try:
        state.fetch()
        stories = state.stories_since(start)
        snaps = [s for p in sorted({state.month_path("snapshots", start), state.month_path("snapshots", now)})
                 for s in state.read_lines(p) if dt.datetime.fromisoformat(s["time_utc"]) >= start]
    except Exception as e:  # noqa: BLE001
        stories, snaps = [], []
        errors.append(f"history: {e}")
    cl_now = state.price_fields(live).get("cl_tm")
    for s in stories:
        at = (s.get("prices") or {}).get("cl_tm")
        s["cl_move_since"] = round(cl_now - at, 2) if (cl_now is not None and at is not None) else None
    tally = {k: sum(1 for s in stories if s.get("sentiment") == k) for k in
             ("Bullish", "Slightly Bullish", "Neutral", "Slightly Bearish", "Bearish")}
    top = sorted(stories, key=lambda s: (IMPACT_RANK.get(s.get("impact"), 0), s["sent_utc"]), reverse=True)[:5]
    json.dump({"generated_utc": now.isoformat(),
               "generated_pkt": now.astimezone(PKT).strftime("%a, %d %b %Y · %I:%M %p PKT"),
               "window_start_utc": start.isoformat(),
               "prices": prices, "live": live, "positioning": pos, "positioning_hourly": hourly, "snapshots": snaps,
               "stories": sorted(stories, key=lambda s: s["sent_utc"]), "top_stories": top,
               "sentiment_tally": tally, "story_count": len(stories),
               "errors": errors + e2 + e3 + e4}, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
