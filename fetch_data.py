#!/usr/bin/env python3
"""Collect everything the Oil Hourly Brief needs and print one JSON document.

Usage: python3 fetch_data.py [--since ISO8601] [--max-articles N] > data.json

Standard library only. Every source is wrapped so one failure never stops the run;
failures are listed under "errors".
"""
import argparse
import datetime as dt
import email.utils
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130 Safari/537.36")
PKT = dt.timezone(dt.timedelta(hours=5))
UTC = dt.timezone.utc

# name, feed url, access ("full" = article text readable, "headline" = feed summary only), filter_oil
FEEDS = [
    ("OilPrice", "https://oilprice.com/rss/main", "full", False),
    ("Rigzone", "https://www.rigzone.com/news/rss/rigzone_latest.aspx", "full", False),
    ("EIA", "https://www.eia.gov/rss/todayinenergy.xml", "full", True),
    ("CNBC Energy", "https://www.cnbc.com/id/19836768/device/rss/rss.html", "full", False),
    ("Guardian", "https://www.theguardian.com/business/oil/rss", "full", False),
    ("BBC", "https://feeds.bbci.co.uk/news/business/rss.xml", "full", True),
    ("FXStreet", "https://www.fxstreet.com/rss/news", "full", True),
    ("Offshore-Energy", "https://www.offshore-energy.biz/feed", "full", True),
    ("gCaptain", "https://gcaptain.com/feed/", "full", True),
    ("NGI", "https://www.naturalgasintel.com/feed/", "full", True),
    ("World Oil", "https://www.worldoil.com/rss?feed=news", "full", False),
    ("Google News", "https://news.google.com/rss/search?q=%22crude+oil%22+OR+WTI+OR+Brent+OR+OPEC+when:1d&hl=en-US&gl=US&ceid=US:en", "headline", False),
    ("Investing.com", "https://www.investing.com/rss/news_11.rss", "headline", True),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "headline", True),
    ("FT", "https://www.ft.com/oil?format=rss", "headline", False),
    ("Nasdaq", "https://www.nasdaq.com/feed/rssoutbound?category=Commodities", "headline", True),
    ("FXEmpire", "https://www.fxempire.com/api/v1/en/articles/rss/news", "headline", True),
]

OIL_RE = re.compile(
    r"\b(crude|oil|wti|brent|opec|petroleum|barrels?|bpd|refiner(y|ies)|tankers?|"
    r"gasoline|diesel|distillates?|eia|rig count|shale|lng|natural gas)\b", re.I)


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def get_json(url, timeout=20):
    return json.loads(get(url, timeout))


def post_json(url, body, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def futures_open(now):
    """CME crude futures hours: Sun 18:00 to Fri 17:00 US Eastern, with a daily 17:00-18:00 break."""
    from zoneinfo import ZoneInfo
    et = now.astimezone(ZoneInfo("America/New_York"))
    wd, h = et.weekday(), et.hour  # Mon=0 .. Sun=6
    if wd == 5 or (wd == 4 and h >= 17) or (wd == 6 and h < 18):
        return False
    return h != 17


def clean(text):
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.strptime(s.strip(), "%b %d, %Y %H:%M GMT")
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


# ---------------------------------------------------------------- prices
def prices():
    out, errors = {}, []
    now = dt.datetime.now(UTC)
    # Live oil prices from Hyperliquid's oracle, which tracks the NYMEX CL / ICE Brent futures 24/7.
    try:
        meta, ctxs = post_json("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs", "dex": "xyz"})
        oracle = {u["name"]: c for u, c in zip(meta["universe"], ctxs)}
        start = int((now - dt.timedelta(minutes=61)).timestamp() * 1000)
        for coin, key in (("xyz:CL", "CL"), ("xyz:BRENTOIL", "BRENT")):
            ex = {"source": "Hyperliquid", "symbol": coin, "last": oracle[coin]["oraclePx"],
                  "prev_day": oracle[coin].get("prevDayPx"), "market_open": futures_open(now)}
            try:
                bars = post_json("https://api.hyperliquid.xyz/info", {"type": "candleSnapshot", "req": {
                    "coin": coin, "interval": "1m", "startTime": start, "endTime": int(now.timestamp() * 1000)}})
                if len(bars) > 1:
                    ex["change_1h"] = round(float(bars[-1]["c"]) - float(bars[0]["c"]), 2)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Hyperliquid 1h {coin}: {e}")
            out.setdefault(key, {})["exchange"] = ex
    except Exception as e:  # noqa: BLE001
        errors.append(f"Hyperliquid prices: {e}")
    for sym, key in (("CLUSDT", "CL"), ("BZUSDT", "BRENT")):
        try:
            t = get_json(f"https://www.binance.com/fapi/v1/ticker/24hr?symbol={sym}")
            p = get_json(f"https://www.binance.com/fapi/v1/premiumIndex?symbol={sym}")
            k = get_json(f"https://www.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&limit=61")
            out.setdefault(key, {})["binance"] = {
                "symbol": sym, "last": t["lastPrice"],
                "change_1h": round(float(t["lastPrice"]) - float(k[0][4]), 2),
                "change_24h": t["priceChange"],
                "change_pct_24h": t["priceChangePercent"], "funding_rate": p["lastFundingRate"],
                "next_funding_ms": p["nextFundingTime"], "mark": p["markPrice"], "index": p["indexPrice"]}
        except Exception as e:  # noqa: BLE001
            errors.append(f"Binance {sym}: {e}")
    return out, errors


# ---------------------------------------------------------------- news
def article_text(url):
    page = get(url, timeout=25)
    paras = [clean(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", page)]
    paras = [p for p in paras if len(p) > 80]
    return " ".join(paras)


def read_feed(feed, since):
    name, url, access, filter_oil = feed
    root = ET.fromstring(get(url).encode("utf-8"))
    items = []
    for it in root.iter("item"):
        if len(items) >= (25 if name == "Google News" else 12):
            break
        title = clean(it.findtext("title"))
        summary = clean(it.findtext("description"))[:600]
        published = parse_date(it.findtext("pubDate"))
        if published and since and published <= since:
            continue
        if filter_oil and not OIL_RE.search(f"{title} {summary}"):
            continue
        items.append({"source": name, "access": access, "title": title,
                      "link": (it.findtext("link") or "").strip(), "summary": summary,
                      "published_utc": published.isoformat() if published else None})
    return items


def news(since, max_articles):
    errors, items = [], []
    with ThreadPoolExecutor(8) as pool:
        futures = {pool.submit(read_feed, f, since): f[0] for f in FEEDS}
        for fut, name in futures.items():
            try:
                items.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name} feed: {e}")
    items.sort(key=lambda x: x["published_utc"] or "", reverse=True)

    full = [i for i in items if i["access"] == "full"][:max_articles]

    def fill(i):
        try:
            text = article_text(i["link"])
            i["text"] = " ".join(text.split()[:900])
            i["words"] = len(text.split())
            if i["words"] < 60:
                i["access"] = "headline"
        except Exception as e:  # noqa: BLE001
            i["access"] = "headline"
            errors.append(f"{i['source']} article: {e}")

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(fill, full))
    return items, errors


# ---------------------------------------------------------------- funding history + calendar
def funding_history():
    out, errors = {}, []
    for sym in ("CLUSDT", "BZUSDT"):
        try:
            rows = get_json(f"https://www.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=3")
            out[sym] = [{"time_utc": dt.datetime.fromtimestamp(r["fundingTime"] / 1000, UTC).isoformat(),
                         "rate": r["fundingRate"]} for r in rows]
        except Exception as e:  # noqa: BLE001
            errors.append(f"Binance funding {sym}: {e}")
    return out, errors


def calendar(now):
    events, errors = [], []
    horizon = now + dt.timedelta(hours=24)
    for week in ("thisweek", "nextweek"):
        try:
            for e in get_json(f"https://nfs.faireconomy.media/ff_calendar_{week}.json"):
                when = dt.datetime.fromisoformat(e["date"]).astimezone(UTC)
                if not now <= when <= horizon:
                    continue
                oil = re.search(r"crude|oil|opec|natural gas", e.get("title", ""), re.I)
                major = e.get("impact") == "High" and e.get("country") in ("USD", "CNY")
                if oil or major:
                    events.append({"time_pkt": when.astimezone(PKT).strftime("%a %H:%M"),
                                   "time_utc": when.isoformat(), "country": e.get("country"),
                                   "title": e.get("title"), "impact": e.get("impact"),
                                   "forecast": e.get("forecast"), "previous": e.get("previous")})
        except Exception as e:  # noqa: BLE001
            if week == "thisweek":
                errors.append(f"ForexFactory {week}: {e}")
    events.sort(key=lambda x: x["time_utc"])
    return events, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="only news published after this ISO time (UTC)")
    ap.add_argument("--max-articles", type=int, default=20)
    a = ap.parse_args()
    now = dt.datetime.now(UTC)
    if a.since:
        since = dt.datetime.fromisoformat(a.since.replace("Z", "+00:00"))
    else:
        # Window = time since the previous scheduled run (routines fire at :32): hourly Mon–Fri UTC,
        # every 4h Sat/Sun UTC. Sat 00:32 follows Fri 23:32 (1h); Mon 00:32 follows Sun 20:32 (4h).
        # 5 extra minutes cover start-up delay; a rare duplicate beats a missed story.
        wd, hr = now.weekday(), now.hour
        weekend = (wd == 5 and hr >= 1) or wd == 6 or (wd == 0 and hr == 0)
        since = now - dt.timedelta(hours=4 if weekend else 1, minutes=5)

    p, e1 = prices()
    n, e2 = news(since, a.max_articles)
    f, e3 = funding_history()
    c, e4 = calendar(now)
    json.dump({"generated_utc": now.isoformat(),
               "generated_pkt": now.astimezone(PKT).strftime("%a, %d %b %Y · %I:%M %p PKT"),
               "news_since_utc": since.isoformat(), "prices": p, "funding_history": f,
               "news": n, "calendar_next_24h": c, "errors": e1 + e2 + e3 + e4},
              sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
