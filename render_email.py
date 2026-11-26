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


# One card for both contracts (approved design, change #7): prices, gap and funding on the lighter top part,
# Binance positioning (crowd, money, flow) on the darker bottom part. Filled with str.format(**price_card_values()).
PRICE_CARD = '''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#1a1f25" style="background-color:#1a1f25;border-radius:6px;"><tr bgcolor="#1a1f25" style="background-color:#1a1f25;"><td width="26%" style="padding:10px 10px 6px 12px;border-bottom:1px solid #1e2329;">&nbsp;</td><td width="37%" style="padding:10px 8px 6px 0;border-bottom:1px solid #1e2329;font-weight:bold;font-size:14px;font-family:Arial,sans-serif;color:#eaecef;">CL</td><td width="37%" style="padding:10px 12px 6px 0;border-bottom:1px solid #1e2329;font-weight:bold;font-size:14px;font-family:Arial,sans-serif;color:#eaecef;">Brent</td></tr><tr bgcolor="#1a1f25" style="background-color:#1a1f25;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;border-bottom:1px solid #1e2329;font-weight:bold;font-size:10px;font-family:Arial,sans-serif;color:#5e6673;letter-spacing:.5px;">TRADITIONAL<br>MARKET</td><td width="37%" valign="top" style="padding:8px 8px 8px 0;border-bottom:1px solid #1e2329;"><div style="font-weight:bold;font-size:22px;font-family:'Courier New',monospace;color:#eaecef;color:{cl_tm_color};line-height:1.1;">{cl_tm_price}</div><div style="padding-top:2px;font-weight:bold;font-size:12px;font-family:Arial,sans-serif;color:#eaecef;color:{cl_tm_chg_color};">{cl_tm_chg} <span style="font-size:12px;font-family:Arial,sans-serif;color:#5e6673;">1h</span></div></td><td width="37%" valign="top" style="padding:8px 12px 8px 0;border-bottom:1px solid #1e2329;"><div style="font-weight:bold;font-size:22px;font-family:'Courier New',monospace;color:#eaecef;color:{bz_tm_color};line-height:1.1;">{bz_tm_price}</div><div style="padding-top:2px;font-weight:bold;font-size:12px;font-family:Arial,sans-serif;color:#eaecef;color:{bz_tm_chg_color};">{bz_tm_chg} <span style="font-size:12px;font-family:Arial,sans-serif;color:#5e6673;">1h</span></div></td></tr><tr bgcolor="#1a1f25" style="background-color:#1a1f25;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;border-bottom:1px solid #1e2329;font-weight:bold;font-size:10px;font-family:Arial,sans-serif;color:#5e6673;letter-spacing:.5px;">BINANCE</td><td width="37%" valign="top" style="padding:8px 8px 8px 0;border-bottom:1px solid #1e2329;"><div style="font-weight:bold;font-size:22px;font-family:'Courier New',monospace;color:#eaecef;color:{cl_bn_color};line-height:1.1;">{cl_bn_price}</div><div style="padding-top:2px;font-weight:bold;font-size:12px;font-family:Arial,sans-serif;color:#eaecef;color:{cl_bn_chg_color};">{cl_bn_chg} <span style="font-size:12px;font-family:Arial,sans-serif;color:#5e6673;">1h</span></div></td><td width="37%" valign="top" style="padding:8px 12px 8px 0;border-bottom:1px solid #1e2329;"><div style="font-weight:bold;font-size:22px;font-family:'Courier New',monospace;color:#eaecef;color:{bz_bn_color};line-height:1.1;">{bz_bn_price}</div><div style="padding-top:2px;font-weight:bold;font-size:12px;font-family:Arial,sans-serif;color:#eaecef;color:{bz_bn_chg_color};">{bz_bn_chg} <span style="font-size:12px;font-family:Arial,sans-serif;color:#5e6673;">1h</span></div></td></tr><tr bgcolor="#1a1f25" style="background-color:#1a1f25;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;font-weight:bold;font-size:10px;font-family:Arial,sans-serif;color:#5e6673;letter-spacing:.5px;"><div style="line-height:20px;">GAP</div><div style="line-height:20px;white-space:nowrap;">FUNDING <span style="font-weight:normal;">4H</span></div></td><td width="37%" valign="top" style="padding:8px 8px 8px 0;"><div style="line-height:20px;"><span style="font-weight:bold;font-size:13px;font-family:'Courier New',monospace;color:#eaecef;color:{cl_gap_color};">{cl_gap}</span></div><div style="line-height:20px;"><span style="font-weight:bold;font-size:12px;font-family:'Courier New',monospace;color:#eaecef;color:{cl_funding_rate_color};white-space:nowrap;">{cl_funding_rate}</span> <span style="font-weight:bold;font-size:11px;font-family:Arial,sans-serif;color:#848e9c;white-space:nowrap;">{cl_funding_who}</span></div></td><td width="37%" valign="top" style="padding:8px 12px 8px 0;"><div style="line-height:20px;"><span style="font-weight:bold;font-size:13px;font-family:'Courier New',monospace;color:#eaecef;color:{bz_gap_color};">{bz_gap}</span></div><div style="line-height:20px;"><span style="font-weight:bold;font-size:12px;font-family:'Courier New',monospace;color:#eaecef;color:{bz_funding_rate_color};white-space:nowrap;">{bz_funding_rate}</span> <span style="font-weight:bold;font-size:11px;font-family:Arial,sans-serif;color:#848e9c;white-space:nowrap;">{bz_funding_who}</span></div></td></tr><tr><td colspan="3" bgcolor="#2b3139" style="background-color:#2b3139;height:1px;line-height:1px;font-size:0;">&nbsp;</td></tr><tr bgcolor="#12161a" style="background-color:#12161a;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;border-bottom:1px solid #1e2329;font-weight:bold;font-size:10px;font-family:Arial,sans-serif;color:#5e6673;letter-spacing:.5px;">CROWD</td><td width="37%" valign="top" style="padding:8px 8px 8px 0;border-bottom:1px solid #1e2329;"><div style="font-weight:bold;font-size:12px;font-family:'Courier New',monospace;color:#eaecef;">{cl_long_pct}% long</div><div style="padding-top:4px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr bgcolor="#12161a" style="background-color:#12161a;"><td width="{cl_long_w}%" height="5" bgcolor="#0ecb81" style="background-color:#0ecb81;font-size:0;line-height:0;">&nbsp;</td><td width="{cl_short_w}%" height="5" bgcolor="#f6465d" style="background-color:#f6465d;font-size:0;line-height:0;">&nbsp;</td></tr></table></div><div style="padding-top:4px;font-weight:bold;font-size:11px;font-family:Arial,sans-serif;color:#eaecef;color:{cl_crowd_color};">{cl_crowd_read}</div><div style="font-size:10px;font-family:Arial,sans-serif;color:#5e6673;">L/S {cl_ls_now}, was {cl_ls_24h}</div></td><td width="37%" valign="top" style="padding:8px 12px 8px 0;border-bottom:1px solid #1e2329;"><div style="font-weight:bold;font-size:12px;font-family:'Courier New',monospace;color:#eaecef;">{bz_long_pct}% long</div><div style="padding-top:4px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr bgcolor="#12161a" style="background-color:#12161a;"><td width="{bz_long_w}%" height="5" bgcolor="#0ecb81" style="background-color:#0ecb81;font-size:0;line-height:0;">&nbsp;</td><td width="{bz_short_w}%" height="5" bgcolor="#f6465d" style="background-color:#f6465d;font-size:0;line-height:0;">&nbsp;</td></tr></table></div><div style="padding-top:4px;font-weight:bold;font-size:11px;font-family:Arial,sans-serif;color:#eaecef;color:{bz_crowd_color};">{bz_crowd_read}</div><div style="font-size:10px;font-family:Arial,sans-serif;color:#5e6673;">L/S {bz_ls_now}, was {bz_ls_24h}</div></td></tr><tr bgcolor="#12161a" style="background-color:#12161a;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;border-bottom:1px solid #1e2329;font-weight:bold;font-size:10px;font-family:Arial,sans-serif;color:#5e6673;letter-spacing:.5px;">MONEY</td><td width="37%" valign="top" style="padding:8px 8px 8px 0;border-bottom:1px solid #1e2329;"><div style="font-weight:bold;font-size:12px;font-family:'Courier New',monospace;color:#eaecef;">{cl_oi_usd}</div><div style="padding-top:2px;font-weight:bold;font-size:11px;font-family:Arial,sans-serif;color:#eaecef;color:{cl_oi_color};">{cl_oi_read}</div><div style="font-size:10px;font-family:Arial,sans-serif;color:#5e6673;">{cl_oi_24h} 24h · {cl_oi_1h} 1h</div></td><td width="37%" valign="top" style="padding:8px 12px 8px 0;border-bottom:1px solid #1e2329;"><div style="font-weight:bold;font-size:12px;font-family:'Courier New',monospace;color:#eaecef;">{bz_oi_usd}</div><div style="padding-top:2px;font-weight:bold;font-size:11px;font-family:Arial,sans-serif;color:#eaecef;color:{bz_oi_color};">{bz_oi_read}</div><div style="font-size:10px;font-family:Arial,sans-serif;color:#5e6673;">{bz_oi_24h} 24h · {bz_oi_1h} 1h</div></td></tr><tr bgcolor="#12161a" style="background-color:#12161a;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;font-weight:bold;font-size:10px;font-family:Arial,sans-serif;color:#5e6673;letter-spacing:.5px;">FLOW 1H</td><td width="37%" valign="top" style="padding:8px 8px 8px 0;"><div style="font-weight:bold;font-size:12px;font-family:'Courier New',monospace;color:#eaecef;">{cl_flow_1h}</div><div style="padding-top:2px;font-weight:bold;font-size:11px;font-family:Arial,sans-serif;color:#eaecef;color:{cl_flow_color};">{cl_flow_read}</div><div style="font-size:10px;font-family:Arial,sans-serif;color:#5e6673;">24h {cl_flow_24h}</div></td><td width="37%" valign="top" style="padding:8px 12px 8px 0;"><div style="font-weight:bold;font-size:12px;font-family:'Courier New',monospace;color:#eaecef;">{bz_flow_1h}</div><div style="padding-top:2px;font-weight:bold;font-size:11px;font-family:Arial,sans-serif;color:#eaecef;color:{bz_flow_color};">{bz_flow_read}</div><div style="font-size:10px;font-family:Arial,sans-serif;color:#5e6673;">24h {bz_flow_24h}</div></td></tr></table>'''


def _money(x):
    return f"${x / 1e9:.2f}B" if x >= 1e9 else f"${x / 1e6:.0f}M"


def _exchange_closed(ex, now):
    if "market_open" in ex:
        return not ex["market_open"]
    if ex.get("last_bar_utc"):
        return now - dt.datetime.fromisoformat(ex["last_bar_utc"]) > dt.timedelta(minutes=30)
    return True


def price_card_values(data, now):
    v, prices, pos = {}, data.get("prices", {}), data.get("positioning", {})
    for p, key, sym in (("cl", "CL", "CLUSDT"), ("bz", "BRENT", "BZUSDT")):
        ex, bn = prices.get(key, {}).get("exchange", {}), prices.get(key, {}).get("binance", {})
        closed = _exchange_closed(ex, now)
        # prices + 1h change
        for kind, src, is_closed in (("tm", ex, closed), ("bn", bn, False)):
            px, ch = num(src.get("last")), num(src.get("change_1h"))
            v[f"{p}_{kind}_price"] = "—" if px is None else f"{px:.2f}"
            v[f"{p}_{kind}_color"] = DIM if (px is None or is_closed) else "#f0b90b"
            if ch is None:
                v[f"{p}_{kind}_chg"], v[f"{p}_{kind}_chg_color"] = ("unavailable" if px is None else "—"), DIM
            else:
                arrow, col = ("▲", GREEN) if ch > 0 else ("▼", RED) if ch < 0 else ("■", GREY)
                v[f"{p}_{kind}_chg"], v[f"{p}_{kind}_chg_color"] = f"{arrow} {signed(ch)}", DIM if is_closed else col
        # gap
        a, b = num(ex.get("last")), num(bn.get("last"))
        if a is None or b is None:
            v[f"{p}_gap"], v[f"{p}_gap_color"] = "—", DIM
        else:
            g = b - a
            v[f"{p}_gap"], v[f"{p}_gap_color"] = signed(g), GREEN if g > 0 else RED if g < 0 else GREY
        # funding: Binance keeps trading 24/7 but holds funding at 0 while NYMEX/ICE are closed.
        r = num(bn.get("funding_rate"))
        if r is None:
            v.update({f"{p}_funding_rate": "—", f"{p}_funding_rate_color": DIM,
                      f"{p}_funding_who": f'<span style="color:{DIM};">unavailable</span>'})
        elif r == 0:
            why = "" if not closed else f' <span style="color:{DIM};font-weight:normal;">· paused, NYMEX/ICE closed</span>'
            v.update({f"{p}_funding_rate": "0.000%", f"{p}_funding_rate_color": GREY, f"{p}_funding_who": "Nobody pays" + why})
        else:
            (pa, pc), (ra, rc) = (("Shorts", RED), ("Longs", GREEN)) if r < 0 else (("Longs", GREEN), ("Shorts", RED))
            v.update({f"{p}_funding_rate": signed(r * 100, 3) + "%", f"{p}_funding_rate_color": "#eaecef",
                      f"{p}_funding_who": f'<span style="color:{pc};">{pa}</span> <span style="color:{DIM};font-weight:normal;">pay</span> '
                                          f'<span style="color:{rc};">{ra}</span>'})
        # positioning
        q = pos.get(sym)
        if not q:
            off = {"read": "unavailable", "color": DIM}
            v.update({f"{p}_long_pct": "—", f"{p}_long_w": "50", f"{p}_short_w": "50", f"{p}_ls_now": "—", f"{p}_ls_24h": "—",
                      f"{p}_oi_usd": "—", f"{p}_oi_24h": "—", f"{p}_oi_1h": "—", f"{p}_flow_1h": "—", f"{p}_flow_24h": "—"})
            for k in ("crowd", "oi", "flow"):
                v[f"{p}_{k}_read"], v[f"{p}_{k}_color"] = off["read"], off["color"]
            continue
        lp, o, t = q["long_pct"], q["oi_change_pct_24h"], q["taker_buy_sell_1h"]
        crowd = (("Crowd heavily long", GREEN) if lp >= 60 else ("Crowd leans long", GREEN) if lp > 52 else
                 ("Crowd split", GREY) if lp >= 48 else ("Crowd leans short", RED) if lp > 40 else ("Crowd heavily short", RED))
        money = ("Fresh money in", GREEN) if o >= 2 else ("Money leaving", RED) if o <= -2 else ("Steady money", GREY)
        flow = (("Buyers chasing", GREEN) if t > 1.10 else ("Buyers edging ahead", GREEN) if t > 1.02 else
                ("Balanced", GREY) if t >= 0.98 else ("Sellers edging ahead", RED) if t >= 0.90 else ("Sellers hitting bids", RED))
        f24 = q.get("taker_buy_sell_24h")
        v.update({f"{p}_long_pct": f"{lp:.1f}", f"{p}_long_w": str(round(lp)), f"{p}_short_w": str(100 - round(lp)),
                  f"{p}_crowd_read": crowd[0], f"{p}_crowd_color": crowd[1],
                  f"{p}_ls_now": f"{q['long_short_ratio']:.2f}", f"{p}_ls_24h": f"{q['long_short_ratio_24h_ago']:.2f}",
                  f"{p}_oi_usd": _money(q["oi_usd"]), f"{p}_oi_read": money[0], f"{p}_oi_color": money[1],
                  f"{p}_oi_24h": signed(o) + "%",
                  f"{p}_oi_1h": "—" if q.get("oi_change_pct_1h") is None else signed(q["oi_change_pct_1h"]) + "%",
                  f"{p}_flow_1h": f"{t:.2f}", f"{p}_flow_read": flow[0], f"{p}_flow_color": flow[1],
                  f"{p}_flow_24h": "—" if f24 is None else f"{f24:.2f}"})
    return v


def prices_section(data, now):
    return ('\n  <!-- PRICES -->\n  <tr><td style="padding:20px 20px 6px;">\n'
            + PRICE_CARD.format(**price_card_values(data, now)) + '\n  </td></tr>\n')


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


def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return dt.date(year, month, (h + l - 7 * m + 114) % 31 + 1)


def us_market_holidays(year):
    """NYMEX/US market holidays (observed dates)."""
    def nth(month, weekday, n):  # n-th weekday of month; n=-1 for last
        if n > 0:
            d = dt.date(year, month, 1)
            return d + dt.timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
        d = dt.date(year, month + 1, 1) - dt.timedelta(days=1) if month < 12 else dt.date(year, 12, 31)
        return d - dt.timedelta(days=(d.weekday() - weekday) % 7)

    def observed(d):
        return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d
    return {observed(dt.date(year, 1, 1)), nth(1, 0, 3), nth(2, 0, 3), _easter(year) - dt.timedelta(days=2),
            nth(5, 0, -1), observed(dt.date(year, 6, 19)), observed(dt.date(year, 7, 4)), nth(9, 0, 1),
            nth(11, 3, 4), observed(dt.date(year, 12, 25))}


def fixed_events(now):
    """Weekly oil releases not always in the ForexFactory feed, in US Eastern time (handles daylight saving).

    EIA releases are left to ForexFactory for the current week (it carries holiday changes); they are only
    filled in here for dates beyond that week. In a week with a market holiday on or before the release day,
    the release moves one day later; Baker Hughes moves to Wednesday in Thanksgiving week; CFTC is skipped in
    holiday weeks (it moves to the next Monday)."""
    spec = [(1, 16, 30, "API weekly crude inventory report", "API"),        # Tue 4:30 PM ET
            (2, 10, 30, "EIA weekly crude inventories", "EIA"),             # Wed 10:30 AM ET
            (3, 10, 30, "EIA natural gas storage", "EIA"),                  # Thu 10:30 AM ET
            (4, 13, 0, "Baker Hughes rig count", "BH"),                     # Fri 1:00 PM ET
            (4, 15, 30, "CFTC Commitments of Traders report", "CFTC")]      # Fri 3:30 PM ET
    out = []
    today_et = now.astimezone(ET).date()
    ff_week_end = today_et + dt.timedelta(days=(5 - today_et.weekday()) % 7)  # ForexFactory week runs Sun-Sat
    for d in range(-1, 9):
        week_start = today_et - dt.timedelta(days=today_et.weekday()) + dt.timedelta(weeks=d // 7)
        if d % 7:
            continue
        holidays = us_market_holidays(week_start.year) | us_market_holidays(week_start.year + 1)
        week_holidays = [week_start + dt.timedelta(days=i) for i in range(5)
                         if week_start + dt.timedelta(days=i) in holidays]
        for wd, hh, mm, title, kind in spec:
            day = week_start + dt.timedelta(days=wd)
            if kind == "EIA" and day <= ff_week_end:
                continue
            if kind == "CFTC" and week_holidays:
                continue
            if kind == "BH" and any(h.month == 11 and h.weekday() == 3 for h in week_holidays):
                day = week_start + dt.timedelta(days=2)  # Thanksgiving week: Wednesday
            elif kind in ("API", "EIA") and any(h <= day for h in week_holidays):
                day += dt.timedelta(days=1)
            if day in holidays:
                continue
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
FOOT_TEMPLATE = '''
  <!-- FOOTER -->
  <tr><td bgcolor="#07090c" style="background:#07090c;padding:14px 20px;border-top:1px solid #1e2329;font:11px/1.5 Arial,sans-serif;color:#5e6673;">
    Sources: {sources}.<br>
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
                     + sentiment_section(stories) + next24_section(data, analysis, now)
                     + FOOT_TEMPLATE.replace("{sources}", E(", ".join(data.get("sources_ok") or ["see routine log"])))))


if __name__ == "__main__":
    main()
