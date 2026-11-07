#!/usr/bin/env python3
"""Render the Oil Hourly Brief HTML email from fetched data + Claude's analysis.

Usage: python3 render_email.py data.json analysis.json > email.html

The markup and colors mirror email-template-dark.html exactly; only the values change.

analysis.json:
{
  "stories": [{
    "headline": str, "link": str, "source": str,          # source = site the link points to
    "sources_count": int, "headline_only": bool,
    "sentiment": "Bullish|Slightly Bullish|Neutral|Slightly Bearish|Bearish",
    "impact": "High|Medium|Low", "horizon": "Short-term|Medium-term|Long-term",
    "region": str, "summary": str, "why": str
  }],
  "extra_events": [{"time_utc": ISO8601, "title": str, "short": str}]   # e.g. OPEC+ meetings from the news
}
"""
import datetime as dt
import html
import json
import re
import sys
from zoneinfo import ZoneInfo

PKT = dt.timezone(dt.timedelta(hours=5))
UTC = dt.timezone.utc
ET = ZoneInfo("America/New_York")
E = html.escape

SENT = {  # label: (score, tag bg, tag fg, grid cell bg)
    "Bearish": (-2, "#2a1215", "#f6465d", "#2a1215"),
    "Slightly Bearish": (-1, "#24161a", "#f59aa6", "#24161a"),
    "Neutral": (0, "#1e2329", "#b7bdc6", "#1e2329"),
    "Slightly Bullish": (1, "#102219", "#7fd9ac", "#102219"),
    "Bullish": (2, "#0d2a1e", "#0ecb81", "#0d2a1e"),
}
SENT_ORDER = ["Bearish", "Slightly Bearish", "Neutral", "Slightly Bullish", "Bullish"]
IMPACT = {"High": (3, "#2d1a0c", "#ff7a1a"), "Medium": (2, "#2b2508", "#ffd60a"), "Low": (1, "#2a2818", "#fff4c2")}
HORIZON = {"Short-term": ("#0f1f33", "#4ea1ff"), "Medium-term": ("#1f1733", "#a78bfa"), "Long-term": ("#0b2422", "#2ec4b6")}
SOURCE_NAMES = {"FT": "Financial Times"}

# PKT open hours [start, end) per region, and bar color (from the template)
SESSIONS = [
    ("Sydney", [(1, 10)], "#5e6673"),
    ("Tokyo", [(5, 14)], "#a78bfa"),
    ("Shanghai", [(6, 12), (18, 24)], "#2ec4b6"),
    ("London", [(13, 22)], "#4ea1ff"),
    ("New York", [(18, 24), (0, 3)], "#ff8c3a"),
]
RED, GREEN, GREY, DIM = "#f6465d", "#0ecb81", "#848e9c", "#5e6673"


def tag(text, bg, fg, bold=True):
    b = "font-weight:bold;" if bold else ""
    return (f'<span style="background:{bg};color:{fg};padding:2px 6px;border-radius:4px;display:inline-block;'
            f'white-space:nowrap;margin:0 0 4px 0;{b}">{E(text)}</span> ')


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def signed(x, nd=2):
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.{nd}f}"


# ---------------------------------------------------------------- header + prices
def header(now):
    p = now.astimezone(PKT)
    when = f"{p:%a}, {p.day} {p:%b %Y} · {p.strftime('%I:%M %p').lstrip('0')} PKT · {now:%H:%M} UTC"
    return f'''  <!-- HEADER -->
  <tr><td bgcolor="#07090c" style="background:#07090c;padding:16px 20px;border-bottom:1px solid #1e2329;">
    <div style="font:bold 18px Arial,sans-serif;color:#eaecef;letter-spacing:.5px;">Oil Hourly Brief</div>
    <div style="font:12px Arial,sans-serif;color:#848e9c;margin-top:4px;">{when}</div>  </td></tr>
'''


def price_cell(px, chg, size, border, closed=False):
    if px is None:
        return (f'<td valign="top" style="padding:12px 0;{border}"><span style="font:12px \'Courier New\',monospace;'
                f'color:#5e6673;">unavailable</span></td>')
    pc = DIM if closed else "#f0b90b"
    if chg is None:
        line = ""
    else:
        arrow, col = ("▲", GREEN) if chg > 0 else ("▼", RED) if chg < 0 else ("■", GREY)
        if closed:
            col = DIM
        line = (f'\n          <div style="font:bold 12px Arial,sans-serif;color:{col};">{arrow} {signed(chg)} '
                f'<span style="font-weight:normal;color:#5e6673;">1h</span></div>')
    return (f'<td valign="top" style="padding:12px 0;{border}">\n'
            f'          <div style="font:bold {size}px \'Courier New\',Courier,monospace;color:{pc};line-height:1.1;">{px:.2f}</div>{line}\n'
            f'        </td>')


def price_row(label, key, prices, size, last, now):
    border = "" if last else "border-bottom:1px solid #1e2329;"
    ex = prices.get(key, {}).get("exchange", {})
    bn = prices.get(key, {}).get("binance", {})
    ex_px, bn_px = num(ex.get("last")), num(bn.get("last"))
    closed = True
    if "market_open" in ex:
        closed = not ex["market_open"]
    elif ex.get("last_bar_utc"):
        age = now - dt.datetime.fromisoformat(ex["last_bar_utc"])
        closed = age > dt.timedelta(minutes=30)
    if ex_px is not None and bn_px is not None:
        gap = bn_px - ex_px
        gcol = GREEN if gap > 0 else RED if gap < 0 else GREY
        gap_html = f'<div style="font:bold 16px \'Courier New\',Courier,monospace;color:{gcol};">{signed(gap)}</div>'
    else:
        gap_html = '<div style="font:bold 16px \'Courier New\',Courier,monospace;color:#5e6673;">—</div>'
    return f'''      <!-- {label} -->
      <tr>
        <td valign="top" style="padding:14px 0 12px;{border}">
          <div style="font:bold 15px Arial,sans-serif;color:#eaecef;">{label}</div>
        </td>
        {price_cell(ex_px, num(ex.get("change_1h")), size, border, closed)}
        {price_cell(bn_px, num(bn.get("change_1h")), size, border)}
        <td valign="top" align="right" style="padding:14px 0 12px;{border}">
          {gap_html}
        </td>
      </tr>
'''


def funding_row(label, rate, last, futures_open=True):
    border = "" if last else "border-bottom:1px solid #1e2329;"
    r = num(rate)
    if r is None:
        who = '<span style="color:#5e6673;">unavailable</span>'
        val = ""
    elif r == 0:
        # Binance keeps trading 24/7 but holds funding at 0 while NYMEX/ICE are closed.
        why = "" if futures_open else ' <span style="color:#5e6673;">· paused while NYMEX/ICE closed</span>'
        who = f'<span style="color:#848e9c;">Nobody pays</span>{why}'
        val = (f'<span style="font:bold 13px \'Courier New\',monospace;color:#848e9c;">0.000%</span> '
               f'<span style="font:10px Arial,sans-serif;color:#5e6673;">per 4h</span>')
    else:
        payer, payee = (("Shorts", RED), ("Longs", GREEN)) if r < 0 else (("Longs", GREEN), ("Shorts", RED))
        who = (f'<b style="color:{payer[1]};">{payer[0]}</b> <span style="color:#5e6673;">pay</span> '
               f'<b style="color:{payee[1]};">{payee[0]}</b>')
        val = (f'<span style="font:bold 13px \'Courier New\',monospace;color:#eaecef;">{signed(r * 100, 3)}%</span> '
               f'<span style="font:10px Arial,sans-serif;color:#5e6673;">per 4h</span>')
    return f'''      <tr>
        <td width="22%" style="padding:7px 0 7px 12px;{border}font:bold 12px Arial,sans-serif;color:#eaecef;">{label}</td>
        <td style="padding:7px 0;{border}font:12px Arial,sans-serif;color:#848e9c;">{who}</td>
        <td align="right" style="padding:7px 12px 7px 0;{border}white-space:nowrap;">{val}</td>
      </tr>
'''


def prices_section(data, now):
    p = data.get("prices", {})
    fut_open = p.get("CL", {}).get("exchange", {}).get("market_open", True)
    return f'''
  <!-- PRICES -->
  <tr><td style="padding:20px 20px 6px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-family:Arial,sans-serif;">
      <tr style="font:bold 10px Arial,sans-serif;color:#5e6673;letter-spacing:1px;">
        <td width="16%" style="padding:0 0 8px;border-bottom:1px solid #1e2329;">&nbsp;</td>
        <td width="33%" style="padding:0 0 8px;border-bottom:1px solid #1e2329;color:#b7bdc6;">TRADITIONAL MARKET</td>
        <td width="33%" style="padding:0 0 8px;border-bottom:1px solid #1e2329;color:#b7bdc6;">BINANCE</td>
        <td width="18%" align="right" style="padding:0 0 8px;border-bottom:1px solid #1e2329;color:#b7bdc6;">GAP</td>
      </tr>
{price_row("CL", "CL", p, 30, False, now)}{price_row("BRENT", "BRENT", p, 22, True, now)}    </table>

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#161a1e" style="background:#161a1e;border-radius:6px;margin-top:10px;">
      <tr><td colspan="3" style="padding:8px 12px 2px;font:bold 10px Arial,sans-serif;color:#5e6673;letter-spacing:1px;">BINANCE FUNDING</td></tr>
{funding_row("CL", p.get("CL", {}).get("binance", {}).get("funding_rate"), False, fut_open)}{funding_row("Brent", p.get("BRENT", {}).get("binance", {}).get("funding_rate"), True, fut_open)}    </table>
  </td></tr>
'''


# ---------------------------------------------------------------- news
def section_title(title, right):
    return f'''    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:2px solid #2b3139;">
      <tr>
        <td style="padding-top:14px;">
          <span style="display:inline-block;width:4px;height:18px;background:#eaecef;vertical-align:middle;"></span>
          <span style="font:bold 18px Arial,sans-serif;color:#eaecef;letter-spacing:3px;vertical-align:middle;padding-left:8px;">{title}</span>
        </td>
        <td align="right" style="padding-top:14px;font:11px Arial,sans-serif;color:#848e9c;">
          {right}
        </td>
      </tr>
    </table>'''


def card(s):
    tags = ""
    if s.get("headline_only"):
        tags += ('<span style="background:transparent;color:#848e9c;border-radius:4px;display:inline-block;'
                 'white-space:nowrap;border:1px dashed #3c434d;padding:1px 6px;margin:0 0 4px 0;">Headline only</span> ')
    _, sbg, sfg, _ = SENT[s["sentiment"]]
    _, ibg, ifg = IMPACT[s["impact"]]
    hbg, hfg = HORIZON[s["horizon"]]
    tags += tag(s["sentiment"], sbg, sfg)
    tags += tag(s["impact"], ibg, ifg)
    tags += tag(s["horizon"], hbg, hfg, bold=False)
    if s.get("region"):
        tags += tag(s["region"], "#1e2329", "#b7bdc6", bold=False)
    n = int(s.get("sources_count") or 1)
    link = E(s["link"], quote=True)
    src = E(SOURCE_NAMES.get(s["source"], s["source"]))
    return f'''    <div style="padding:10px 0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#161a1e" style="background:#161a1e;border:1px solid #1e2329;border-radius:6px;">
      <tr>
        <td valign="top" style="padding:12px 14px;">
          <div style="font:11px/22px Arial,sans-serif;margin-bottom:6px;">{tags}</div>
          <div style="font:bold 15px Arial,sans-serif;line-height:1.35;"><a href="{link}" target="_blank" style="color:#eaecef;text-decoration:underline;text-decoration-color:#3c434d;">{E(s["headline"])}</a></div>
          <div style="font:13px/1.65 Arial,sans-serif;margin-top:8px;color:#b7bdc6;">{E(s["summary"])}</div>
          <div style="padding-top:10px;"><div style="font:13px/1.5 Arial,sans-serif;padding-top:8px;border-top:1px solid #1e2329;color:#eaecef;"><b style="color:#eaecef;">Why it matters:</b> {E(s["why"])}</div></div>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;"><tr>
            <td style="font:12px Arial,sans-serif;"><a href="{link}" target="_blank" style="color:#4ea1ff;text-decoration:none;font-weight:bold;">Read on {src} &rarr;</a></td>
            <td align="right" style="font:11px Arial,sans-serif;"><span style="background:#1e2329;color:#b7bdc6;padding:2px 6px;border-radius:4px;display:inline-block;white-space:nowrap;font-weight:bold;">{n} source{"s" if n != 1 else ""}</span></td>
          </tr></table>
        </td>
      </tr>
    </table>
    </div>
'''


def news_section(stories):
    head = f'''
  <!-- ARTICLES -->
  <tr><td style="padding:22px 20px 4px;">
{section_title("NEWS", f'<b style="color:#eaecef;">{len(stories)}</b> new &nbsp;·&nbsp; sorted by impact')}
  </td></tr>
'''
    if not stories:
        return head + '''  <tr><td style="padding:14px 20px 4px;font:13px Arial,sans-serif;color:#848e9c;">No new oil stories since the last email.</td></tr>
'''
    cards = [card(s) for s in stories]
    body = "".join(cards)  # every card shown on every client (no CSS toggle)
    return head + '  <tr><td style="padding:0 20px;">\n' + body + '  </td></tr>\n'


# ---------------------------------------------------------------- sentiment
def score_of(stories):
    w = sum(IMPACT[s["impact"]][0] for s in stories)
    return sum(IMPACT[s["impact"]][0] * SENT[s["sentiment"]][0] for s in stories) / w if w else None


def label_of(score):
    if score >= 1.0:
        return "Bullish"
    if score >= 0.3:
        return "Slightly Bullish"
    if score > -0.3:
        return "Neutral"
    if score > -1.0:
        return "Slightly Bearish"
    return "Bearish"


def bar_row(name, color, stories, last):
    border = "" if last else "border-bottom:1px solid #1e2329;"
    sc = score_of(stories)
    n = len(stories)
    count = f"{n} article{'s' if n != 1 else ''}"
    if sc is None:
        return (f'<tr><td width="18%" style="padding:0;{border}font:bold 12px Arial,sans-serif;color:{color};">{name}</td>'
                f'<td width="24%" style="padding:0;{border}font:bold 12px Arial,sans-serif;color:#5e6673;">—</td>'
                f'<td width="38%" style="padding:0 10px;{border}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                f'<td width="50%" height="38" style="font-size:0;">&nbsp;</td><td width="50%" height="38" style="border-left:2px solid #5e6673;font-size:0;">&nbsp;</td>'
                f'</tr></table></td><td align="right" style="padding:0;{border}font:11px Arial,sans-serif;color:#848e9c;">{count}</td></tr>')
    lab = label_of(sc)
    col = SENT[lab][2]
    pct = max(2, min(100, round(abs(sc) / 2 * 100)))
    val = f"{'+' if sc >= 0 else '−'}{abs(sc):.1f}"
    if sc < 0:
        inner = (f'<td width="50%" height="38" valign="middle"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                 f'<td width="{100 - pct}%" align="right" style="padding-right:5px;font:bold 11px \'Courier New\',monospace;color:#eaecef;white-space:nowrap;">{val}</td>'
                 f'<td width="{pct}%" height="12" bgcolor="{col}" style="background:{col};font-size:0;line-height:0;">&nbsp;</td></tr></table></td>'
                 f'<td width="50%" height="38" style="border-left:2px solid #5e6673;font-size:0;">&nbsp;</td>')
    else:
        inner = (f'<td width="50%" height="38" style="font-size:0;">&nbsp;</td>'
                 f'<td width="50%" height="38" valign="middle" style="border-left:2px solid #5e6673;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                 f'<td width="{pct}%" height="12" bgcolor="{col}" style="background:{col};font-size:0;line-height:0;">&nbsp;</td>'
                 f'<td width="{100 - pct}%" align="left" style="padding-left:5px;font:bold 11px \'Courier New\',monospace;color:#eaecef;white-space:nowrap;">{val}</td></tr></table></td>')
    return (f'<tr><td width="18%" style="padding:0;{border}font:bold 12px Arial,sans-serif;color:{color};">{name}</td>'
            f'<td width="24%" style="padding:0;{border}font:bold 12px Arial,sans-serif;color:{col};">{lab}</td>'
            f'<td width="38%" style="padding:0 10px;{border}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{inner}</tr></table></td>'
            f'<td align="right" style="padding:0;{border}font:11px Arial,sans-serif;color:#848e9c;">{count}</td></tr>')


def dot(color):
    return (f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background-color:{color};'
            f'border:2px solid {color};vertical-align:middle;margin:1px;"></span>')


def sentiment_section(stories):
    by_h = {h: [s for s in stories if s["horizon"] == h] for h in HORIZON}
    bars = bar_row("Overall", "#eaecef", stories, False)
    for i, (h, (_, hc)) in enumerate(HORIZON.items()):
        bars += bar_row(h, hc, by_h[h], i == 2)
    # Mobile-safe grid: wrapped two-line labels, fixed column widths, gaps from cellspacing (no borders,
    # which dark-mode mail apps recolour to white).
    head_cells = "".join(
        f'<td width="16%" align="center" valign="bottom" style="padding:0 1px 6px;font:bold 10px Arial,sans-serif;color:{SENT[l][2]};line-height:1.2;">'
        f'{l.replace("Slightly ", "Slightly<br>")}<br><b style="font-family:\'Courier New\',monospace;color:#eaecef;">{sum(s["sentiment"] == l for s in stories)}</b></td>'
        for l in SENT_ORDER)
    grid = f'<tr><td width="20%"></td>{head_cells}</tr>'
    for h, (_, hc) in HORIZON.items():
        row = (f'<tr><td width="20%" style="padding:0 4px 0 0;font:bold 11px Arial,sans-serif;color:{hc};line-height:1.2;">'
               f'{h.replace("-term", "")}<br><span style="font-weight:normal;color:#848e9c;">term · </span>'
               f'<b style="font-family:\'Courier New\',monospace;color:#eaecef;">{len(by_h[h])}</b></td>')
        for l in SENT_ORDER:
            cell = sorted((s for s in by_h[h] if s["sentiment"] == l), key=lambda s: -IMPACT[s["impact"]][0])
            bg = SENT[l][3] if cell else "#12161a"
            content = "".join(dot(IMPACT[s["impact"]][2]) for s in cell) or "&nbsp;"
            row += (f'<td width="16%" align="center" height="34" bgcolor="{bg}" style="background-color:{bg};'
                    f'padding:6px 1px;line-height:14px;">{content}</td>')
        grid += row + "</tr>"
    key = (f'Impact: {dot("#ff7a1a")} <span style="color:#ff7a1a;font-weight:bold;">High</span> &nbsp; '
           f'{dot("#ffd60a")} <span style="color:#ffd60a;font-weight:bold;">Medium</span> &nbsp; '
           f'{dot("#fff4c2")} <span style="color:#fff4c2;font-weight:bold;">Low</span> &nbsp;·&nbsp; one dot = one article')
    return f'''
  <!-- SENTIMENT -->
  <tr><td style="padding:22px 20px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:2px solid #2b3139;margin-bottom:12px;">
      <tr>
        <td style="padding-top:14px;">
          <span style="display:inline-block;width:4px;height:18px;background:#eaecef;vertical-align:middle;"></span>
          <span style="font:bold 18px Arial,sans-serif;color:#eaecef;letter-spacing:3px;vertical-align:middle;padding-left:8px;">SENTIMENT</span>
        </td>
        <td align="right" style="padding-top:14px;font:11px Arial,sans-serif;color:#848e9c;">from <b style="color:#eaecef;">{len(stories)}</b> articles</td>
      </tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{bars}</table><div style="font:11px Arial,sans-serif;color:#5e6673;margin-top:8px;">The number on each bar shows how bearish or bullish the news is overall, from −2 (very bearish) to +2 (very bullish). Bigger stories count more: High-impact news counts 3 times, Medium twice and Low once.</div>
<div style="font:bold 10px Arial,sans-serif;color:#5e6673;letter-spacing:1.5px;margin:18px 0 8px;">BREAKDOWN</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="3" style="border-collapse:separate;table-layout:fixed;">{grid}</table><div style="font:11px Arial,sans-serif;color:#848e9c;margin-top:10px;">{key}</div>
  </td></tr>
'''


# ---------------------------------------------------------------- next 24 hours
SHORT = [("crude oil inventories", "EIA"), ("natural gas storage", "NG"), ("api", "API"), ("baker hughes", "Rigs"),
         ("cftc", "COT"), ("fomc", "Fed"), ("federal funds", "Fed"), ("cpi", "CPI"), ("non-farm", "NFP"),
         ("opec", "OPEC+"), ("gdp", "GDP"), ("pmi", "PMI")]


def short_label(title):
    t = title.lower()
    for k, v in SHORT:
        if k in t:
            return v
    return title.split()[0][:6]


def fixed_events(now):
    """Weekly oil releases, defined in US Eastern time (handles daylight saving)."""
    spec = [(1, 16, 30, "API weekly crude inventory report"),            # Tue 4:30 PM ET
            (2, 10, 30, "EIA weekly crude inventories"),                  # Wed 10:30 AM ET
            (3, 10, 30, "EIA natural gas storage"),                       # Thu 10:30 AM ET
            (4, 13, 0, "Baker Hughes rig count"),                         # Fri 1:00 PM ET
            (4, 15, 30, "CFTC Commitments of Traders report")]            # Fri 3:30 PM ET
    out = []
    today_et = now.astimezone(ET).date()
    for d in range(0, 3):
        day = today_et + dt.timedelta(days=d)
        for wd, hh, mm, title in spec:
            if day.weekday() == wd:
                t = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=ET).astimezone(UTC)
                if now <= t <= now + dt.timedelta(hours=24):
                    out.append({"time_utc": t.isoformat(), "title": title})
    return out


def collect_events(data, analysis, now):
    events = [{"time_utc": e["time_utc"], "title": e["title"]} for e in data.get("calendar_next_24h", [])]
    for f in fixed_events(now):  # skip a fixed event if the calendar feed already lists it within the hour
        ft = dt.datetime.fromisoformat(f["time_utc"])
        dupe = any(abs(dt.datetime.fromisoformat(e["time_utc"]) - ft) < dt.timedelta(hours=1)
                   and short_label(e["title"]) == short_label(f["title"]) for e in events)
        if not dupe:
            events.append(f)
    for e in analysis.get("extra_events", []):
        t = dt.datetime.fromisoformat(e["time_utc"].replace("Z", "+00:00"))
        if now <= t <= now + dt.timedelta(hours=24):
            events.append(e)
    for e in events:
        e["t"] = dt.datetime.fromisoformat(e["time_utc"].replace("Z", "+00:00")).astimezone(PKT)
        e.setdefault("short", short_label(e["title"]))
    return sorted(events, key=lambda e: e["t"])


def next24_section(data, analysis, now):
    events = collect_events(data, analysis, now)
    rows = ""
    for i, e in enumerate(events):
        w = "width:160px;" if i == 0 else ""
        when = f"{e['t']:%a} {e['t'].strftime('%I:%M %p').lstrip('0')} PKT"
        rows += (f'      <tr><td style="padding:4px 0;{w}color:#848e9c;white-space:nowrap;">{when}</td>'
                 f'<td style="color:#b7bdc6;">{E(e["title"])}</td></tr>\n')
    if not rows:
        rows = '      <tr><td style="padding:4px 0;color:#848e9c;">No scheduled oil events in the next 24 hours.</td></tr>\n'

    start = now.astimezone(PKT).hour
    hours = [(start + i) % 24 for i in range(24)]
    ev_cols = {}
    for e in events:
        col = int((e["t"].replace(minute=0, second=0, microsecond=0)
                   - now.astimezone(PKT).replace(minute=0, second=0, microsecond=0)).total_seconds() // 3600)
        if 0 <= col < 24:
            ev_cols.setdefault(col, []).append(e["short"])
    lab_style = "font:bold 9px Arial,sans-serif;color:#eaecef;padding-bottom:3px;white-space:nowrap;overflow:visible;"
    top = '<tr><td width="16%" style="font-size:0;">&nbsp;</td>'
    for i in range(24):
        text = "NOW" if i == 0 else "/".join(dict.fromkeys(ev_cols.get(i, []))) or "&nbsp;"
        top += f'<td width="3.5%" align="left" style="{lab_style}">{E(text) if text != "&nbsp;" else text}</td>'
    top += "</tr>"
    region_rows = ""
    for name, spans, color in SESSIONS:
        r = f'      <tr><td width="16%" style="font:11px Arial,sans-serif;color:#b7bdc6;padding:3px 6px 3px 0;">{name}</td>'
        for i, h in enumerate(hours):
            on = any(a <= h < b for a, b in spans)
            bg = color if on else "#12161a"
            left = "border-left:2px solid #eaecef;" if i == 0 else "border-left:2px dotted #eaecef;" if i in ev_cols else ""
            r += (f'<td width="3.5%" height="14" bgcolor="{bg}" style="background:{bg};{left}'
                  f'border-right:1px solid #0b0e11;font-size:0;line-height:0;">&nbsp;</td>')
        region_rows += r + "</tr>\n"
    axis = '      <tr><td width="16%" style="font-size:0;">&nbsp;</td>'
    for i, h in enumerate(hours):
        axis += (f'<td width="3.5%" align="left" style="font:9px \'Courier New\',monospace;color:#5e6673;padding-top:3px;">'
                 f'{f"{h:02d}" if i % 2 == 0 else "&nbsp;"}</td>')
    axis += "</tr>\n"
    return f'''
  <!-- NEXT 24 HOURS -->
  <tr><td style="padding:22px 20px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:2px solid #2b3139;margin-bottom:12px;">
      <tr>
        <td style="padding-top:14px;">
          <span style="display:inline-block;width:4px;height:18px;background:#eaecef;vertical-align:middle;"></span>
          <span style="font:bold 18px Arial,sans-serif;color:#eaecef;letter-spacing:3px;vertical-align:middle;padding-left:8px;">NEXT 24 HOURS</span>
        </td>
        <td align="right" style="padding-top:14px;font:11px Arial,sans-serif;color:#848e9c;"><b style="color:#eaecef;">{len(events)}</b> events &nbsp;·&nbsp; PKT</td>
      </tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font:13px Arial,sans-serif;">
{rows}    </table>
    <div style="font:bold 11px Arial,sans-serif;color:#848e9c;letter-spacing:1px;margin:18px 0 6px;">NEXT 24 HOURS · PKT</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;">
      {top}
{region_rows}{axis}    </table>
  </td></tr>
'''


# ---------------------------------------------------------------- page
HEAD = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="format-detection" content="telephone=no, date=no, address=no, email=no">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
<title>Oil Hourly Brief</title>
</head>
<body style="margin:0;padding:0;background:#05070a;font-family:Arial,Helvetica,sans-serif;color:#eaecef;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;" bgcolor="#05070a">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#05070a" style="background:#05070a;">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#0b0e11" style="max-width:640px;background:#0b0e11;border:1px solid #1e2329;border-radius:8px;overflow:hidden;">

'''
FOOT = '''
  <!-- FOOTER -->
  <tr><td bgcolor="#07090c" style="background:#07090c;padding:14px 20px;border-top:1px solid #1e2329;font:11px/1.5 Arial,sans-serif;color:#5e6673;">
    Sources checked: CNBC, OilPrice, Rigzone, EIA, CNBC Energy, Guardian, BBC, FXStreet, Offshore-Energy, gCaptain, NGI, World Oil, Google News, Investing.com, MarketWatch, FT, Nasdaq, FXEmpire.<br>
    Sentiment, impact and horizon are AI assessments, not financial advice. Generated automatically by a Claude routine.
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>
'''


def validate(stories):
    for i, s in enumerate(stories):
        for field, allowed in (("sentiment", SENT), ("impact", IMPACT), ("horizon", HORIZON)):
            if s.get(field) not in allowed:
                raise SystemExit(f"story {i}: {field}={s.get(field)!r} must be one of {list(allowed)}")
        for field in ("headline", "link", "source", "summary", "why"):
            if not s.get(field):
                raise SystemExit(f"story {i}: missing {field}")


FONT_RE = re.compile(r"font:\s*(bold\s+)?(\d+px)(?:/([\d.]+(?:px)?))?\s+([^;\"]+)")
DIV_MARGIN_RE = re.compile(r'<div style="([^"]*)"')


def _font(m):
    out = []
    if m.group(1):
        out.append("font-weight:bold")
    out.append(f"font-size:{m.group(2)}")
    if m.group(3):
        out.append(f"line-height:{m.group(3)}")
    out.append(f"font-family:{m.group(4).strip()}")
    return ";".join(out)


def _div(m):
    st = m.group(1)
    if "border" in st or "background" in st:
        return m.group(0)  # margin and padding differ visually here; leave as is
    def conv(mm):
        side, value = mm.group(1), mm.group(2).strip()
        if side:  # margin-top / margin-bottom → same padding (no border or background, so it looks identical)
            return f"padding-{side}:{value}"
        v = value.split()  # margin shorthand: keep only the vertical spacing
        top = v[0]
        bottom = v[2] if len(v) >= 3 else v[0]
        return f"padding-top:{top};padding-bottom:{bottom}"
    return '<div style="' + re.sub(r"margin(?:-(top|bottom))?:([^;]+)", conv, st) + '"'


def email_safe(html_text):
    html_text = re.sub(r"([;\"])background:(#[0-9a-fA-F]{3,6}|transparent)", r"\1background-color:\2", html_text)
    """Make every client render the same: longhand fonts (Outlook ignores the shorthand), div
    spacing as padding (Outlook ignores div margins), and no whitespace between tags."""
    html_text = FONT_RE.sub(_font, html_text)
    html_text = DIV_MARGIN_RE.sub(_div, html_text)
    return re.sub(r">\s*\n\s*<", "><", html_text)  # keep single spaces (they separate tags in Outlook)


def main():
    data = json.load(open(sys.argv[1]))
    analysis = json.load(open(sys.argv[2]))
    now = dt.datetime.fromisoformat(data["generated_utc"])
    stories = analysis.get("stories", [])
    validate(stories)
    stories.sort(key=lambda s: -IMPACT[s["impact"]][0])  # stable: keeps Claude's newest-first order within a level
    sys.stdout.write(email_safe(HEAD + header(now) + prices_section(data, now) + news_section(stories)
                     + sentiment_section(stories) + next24_section(data, analysis, now) + FOOT))


if __name__ == "__main__":
    main()
