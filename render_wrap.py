#!/usr/bin/env python3
"""Render the Oil Daily Wrap (approved design, change #11) from wrap_data.py's JSON.

  python3 render_wrap.py /tmp/wrap.json > /tmp/wrap.html

The templates (PAGE and SNIPPETS) are the approved design; FIELDS documents every placeholder's data and rule.
"""
import datetime as dt
import html
import json
import sys
from urllib.parse import urlparse

import render_email as R  # shell, colours, tags and email_safe() shared with the brief

E = html.escape
PKT = dt.timezone(dt.timedelta(hours=5))
GREEN, RED, GREY, DIM, YELLOW, AXIS = R.GREEN, R.RED, R.GREY, R.DIM, "#f0b90b", "#5e6673"
SETTLE_UTC = (19, 30)          # NYMEX settle 2:30 PM New York = 19:30 UTC in winter (18:30 UTC under US daylight saving)
SLOTS = 24                     # hourly columns over the 24-hour window (keeps the email under Gmail's ~102 KB clip)
MAX_OTHER = 20                 # OTHER NEWS rows shown; the rest become one "+N more" line (busy days only)
PRICE_HALF, CROWD_HALF = 36, 22  # px above/below the centre line
BLOCK, BLOCK_GAP = 5, 1          # news block height / gap, px

# ============================================================== TEMPLATES
# Shorthand fonts are fine here: email_safe() expands them, as in render_email.py.
LINE = "border-bottom:1px solid #1e2329;"
LABEL = "font:bold 10px Arial,sans-serif;color:#5e6673;letter-spacing:.5px;"
MONO = "font-family:Arial,Helvetica,sans-serif;font-weight:bold;"  # Arial digits are fixed-width on Android, iOS and desktop

SNIPPETS = {
# ---------------------------------------------------------------- header
"HEADER": '''  <tr><td bgcolor="#07090c" style="background:#07090c;padding:16px 16px;border-bottom:1px solid #1e2329;">
    <div style="font:bold 18px Arial,sans-serif;color:#eaecef;letter-spacing:.5px;">Oil Daily Wrap</div>
    <div style="font:12px Arial,sans-serif;color:#848e9c;margin-top:4px;">{when}</div>
    <div style="font:11px Arial,sans-serif;color:#5e6673;margin-top:2px;">The last 24 hours, from {window_start} PKT yesterday · after NYMEX settlement</div>
  </td></tr>
''',
# ---------------------------------------------------------------- day card (CL | Brent)
"DAY_CARD": '''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#1a1f25" style="background:#1a1f25;border-radius:6px;">'''
    '''<tr bgcolor="#1a1f25" style="background:#1a1f25;"><td width="26%" style="padding:10px 10px 6px 12px;''' + LINE + '''">&nbsp;</td>'''
    '''<td width="37%" style="padding:10px 8px 6px 0;''' + LINE + '''font:bold 14px Arial,sans-serif;color:#eaecef;">CL</td>'''
    '''<td width="37%" style="padding:10px 12px 6px 0;''' + LINE + '''font:bold 14px Arial,sans-serif;color:#eaecef;">Brent</td></tr>'''
    '''<tr bgcolor="#1a1f25" style="background:#1a1f25;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;''' + LINE + LABEL + '''">TRADITIONAL<br>MARKET<br><span style="font-weight:normal;">day change</span></td>{cl_tm_cell}{bz_tm_cell}</tr>'''
    '''<tr bgcolor="#1a1f25" style="background:#1a1f25;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;''' + LINE + LABEL + '''">DAY<br>RANGE<br><span style="font-weight:normal;white-space:nowrap;">open &rarr; <span style="color:#f0b90b;">close</span></span></td>{cl_range_cell}{bz_range_cell}</tr>'''
    '''<tr bgcolor="#1a1f25" style="background:#1a1f25;"><td width="26%" valign="top" style="padding:9px 10px 8px 12px;''' + LABEL + '''">BINANCE<br><span style="font-weight:normal;">day change</span></td>{cl_bn_cell}{bz_bn_cell}</tr>'''
    '''</table>''',
"TM_CELL": '''<td width="37%" valign="top" style="padding:8px {pad} 8px 0;''' + LINE + '''">'''
    '''<div style="font:bold 22px Arial,Helvetica,sans-serif;color:#f0b90b;line-height:1.1;">{close}</div>'''
    '''<div style="padding-top:2px;"><span style="font:bold 12px Arial,sans-serif;color:{chg_color};white-space:nowrap;">{arrow} {chg} <span style="font-weight:normal;">({chg_pct}%)</span></span></div>'''
    '''<div style="font:10px Arial,sans-serif;color:#5e6673;padding-top:2px;white-space:nowrap;">open <span style="''' + MONO + '''color:#848e9c;">{open}</span></div></td>''',
"RANGE_CELL": '''<td width="37%" valign="top" style="padding:8px {pad} 8px 0;''' + LINE + '''">'''
    '''<div style="padding:5px 0 4px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;"><tr>{range_parts}</tr></table></div>'''
    '''<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'''
    '''<td align="left" style="font:10px Arial,Helvetica,sans-serif;color:#848e9c;white-space:nowrap;">L {low}</td>'''
    '''<td align="right" style="font:10px Arial,Helvetica,sans-serif;color:#848e9c;white-space:nowrap;">H {high}</td></tr></table></td>''',
"RANGE_PART": '''<td width="{w}%" height="8" bgcolor="{bg}" style="background:{bg};font-size:0;line-height:0;">&nbsp;</td>''',
"BN_CELL": '''<td width="37%" valign="top" style="padding:8px {pad} 8px 0;">'''
    '''<div style="font:bold 16px Arial,Helvetica,sans-serif;color:#f0b90b;">{close}</div>'''
    '''<div style="padding-top:2px;"><span style="font:bold 11px Arial,sans-serif;color:{chg_color};white-space:nowrap;">{arrow} {chg} <span style="font-weight:normal;">({chg_pct}%)</span></span></div></td>''',
# ---------------------------------------------------------------- THE DAY chart: 3 panels on one 30-min axis
"CHART": '''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;">'''
    '''<tr><td colspan="{slots}" style="padding:14px 0 6px;white-space:nowrap;font:bold 10px Arial,sans-serif;color:#848e9c;letter-spacing:.5px;">PRICE <span style="font-weight:normal;color:#5e6673;">vs open</span>&nbsp;'''
    '''<span style="''' + MONO + '''color:#eaecef;">{open}</span> &nbsp;<span style="font-weight:normal;color:#0ecb81;">high {high_vs_open}</span> · <span style="font-weight:normal;color:#f6465d;">low {low_vs_open}</span></td></tr>'''
    '''<tr style="font-size:0;line-height:0;">{price_cols}</tr><tr>{mark_cells}</tr><tr>{mark_label_cells}</tr>'''
    '''<tr><td colspan="{slots}" style="padding:14px 0 6px;white-space:nowrap;font:bold 10px Arial,sans-serif;color:#848e9c;letter-spacing:.5px;">NEWS &nbsp;'''
    '''<span style="font-weight:normal;color:#0ecb81;white-space:nowrap;">&uarr; {n_bull} bullish</span> · <span style="font-weight:normal;color:#b7bdc6;white-space:nowrap;">{n_neutral} neutral</span> · <span style="font-weight:normal;color:#f6465d;white-space:nowrap;">&darr; {n_bear} bearish</span></td></tr>'''
    '''<tr style="font-size:0;line-height:0;">{news_cols}</tr>'''
    '''<tr><td colspan="{slots}" style="padding:14px 0 6px;white-space:nowrap;font:bold 10px Arial,sans-serif;color:#848e9c;letter-spacing:.5px;">% LONG <span style="font-weight:normal;color:#5e6673;">vs start</span> &nbsp;'''
    '''<span style="''' + MONO + '''color:#eaecef;">{long_start}% &rarr; {long_end}%</span></td></tr>'''
    '''<tr style="font-size:0;line-height:0;">{crowd_cols}</tr><tr>{axis_cells}</tr></table>'''
    '''<div style="font:10px Arial,sans-serif;color:#5e6673;padding-top:6px;">Binance CL · hourly · times PKT · <span style="color:#b7bdc6;">▲</span> top story · <span style="color:#b7bdc6;">■</span> open / high / low / settle · one block = one story</div>''',
# one column of an up/down panel, as ONE flat table: spacer, bar(s) up, 1px centre line, bar(s) down, spacer.
# Heights add up to 2*half+1 so every column lines up. font-size/line-height 0 on the table keeps empty cells at their height.
"COL": '''<td width="{w}%" style="padding-right:1px;"><table width="100%" cellpadding="0" cellspacing="0">{rows}</table></td>''',
"SP": '''<tr><td height="{h}">{line}&nbsp;</td></tr>''',
"FILL": '''<tr><td height="{h}" bgcolor="{color}">{line}&nbsp;</td></tr>''',
"MARK_CELL": '''<td align="center" style="padding-top:4px;line-height:11px;">{mark}</td>''',
"MARK": '''<span style="font:bold 11px Arial,sans-serif;color:{color};">{shape}</span>''',
"MARK_LABEL_CELL": '''<td align="center" style="font:9px Arial,sans-serif;color:#848e9c;white-space:nowrap;line-height:10px;">{label}</td>''',
"AXIS_CELL": '''<td style="font:9px Arial,sans-serif;color:#5e6673;padding-top:4px;white-space:nowrap;">{label}</td>''',
# ---------------------------------------------------------------- THE DAY timeline rows
"TL_ROW": '''<tr><td width="64" valign="top" style="padding:{pad} 8px 0 0;"><div style="font:bold 11px Arial,sans-serif;color:#eaecef;white-space:nowrap;">{time}</div>{left_price}</td>'''
    '''<td width="14" valign="top" style="padding-top:{pad};{rail}"><div style="margin-left:-6px;line-height:12px;">{dot}</div></td>'''
    '''<td valign="top" style="padding:{pad} 0 14px 8px;">{content}</td></tr>''',
"LEFT_PRICE": '''<div style="font:bold 12px Arial,Helvetica,sans-serif;color:{color};padding-top:2px;">{price}</div>''',
"DOT": '''<span style="font:bold 10px Arial,sans-serif;color:{color};">{shape}</span>''',
"MOMENT_CONTENT": '''<div style="font:bold 11px Arial,sans-serif;color:{color};letter-spacing:.5px;">{name}</div>''',
"STORY_CONTENT": '''<div style="font:11px/22px Arial,sans-serif;white-space:nowrap;">{sentiment_tag}{impact_tag}</div>'''
    '''<div style="font:bold 14px Arial,sans-serif;line-height:1.35;"><a href="{link}" target="_blank" style="color:#eaecef;text-decoration:underline;text-decoration-color:#3c434d;">{headline}</a></div>'''
    '''<div style="font:12px/1.5 Arial,sans-serif;color:#b7bdc6;padding-top:4px;"><b style="color:#eaecef;">Why:</b> {why}</div>'''
    '''<div style="font:11px/1.6 Arial,sans-serif;padding-top:4px;color:#848e9c;">{horizon_region} · <span style="color:#4ea1ff;font-weight:bold;white-space:nowrap;">{source} &rarr;</span></div>'''
    '''<div style="font:11px Arial,sans-serif;padding-top:2px;">{move}</div>'''
    '''<div style="padding-top:6px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#12161a" style="background:#12161a;border-radius:4px;table-layout:fixed;"><tr>{traders_cells}</tr></table></div>''',
"MOVE": '''<span style="color:#848e9c;">CL since then</span> <b style="color:{color};">{move}</b>''',
"MOVE_MISSING": '''<span style="color:#5e6673;">CL since: —</span>''',
"TRADERS_CELL": '''<td width="33%" valign="top" style="padding:6px 6px 6px {pad_left};{divider}">'''
    '''<div style="font:bold 9px Arial,sans-serif;color:#5e6673;letter-spacing:.5px;white-space:nowrap;">{label}</div>'''
    '''<div style="font:bold 11px Arial,sans-serif;color:{color};padding-top:2px;">{read}</div>'''
    '''<div style="font:10px Arial,Helvetica,sans-serif;color:#848e9c;white-space:nowrap;">{number}</div></td>''',
"EOD_CONTENT": '''<div style="font:bold 11px Arial,sans-serif;color:#b7bdc6;letter-spacing:.5px;">BINANCE TRADERS BY END OF DAY</div>'''
    '''<div style="padding-top:6px;"><b style="font:bold 12px Arial,sans-serif;color:#eaecef;">CL</b><div style="font:bold 12px/1.6 Arial,sans-serif;">'''
    '''<span style="color:{crowd_color};white-space:nowrap;">{crowd_read}</span> <span style="color:#5e6673;font-weight:normal;">({long_was}%&rarr;{long_now}% long)</span> · '''
    '''<span style="color:{money_color};white-space:nowrap;">{money_read}</span> <span style="color:#5e6673;font-weight:normal;">({money_pct}%)</span> · '''
    '''<span style="color:{flow_color};white-space:nowrap;">{flow_read}</span> <span style="color:#5e6673;font-weight:normal;">({flow})</span></div></div>''',
# ---------------------------------------------------------------- OTHER NEWS rows
"OTHER_ROW": '''<tr><td width="64" valign="top" style="padding:10px 8px 10px 0;{border}"><div style="font:bold 11px Arial,sans-serif;color:#eaecef;white-space:nowrap;">{time}</div>{left_price}</td>'''
    '''<td valign="top" style="padding:8px 0 10px;{border}">'''
    '''<div style="font:11px/22px Arial,sans-serif;white-space:nowrap;">{sentiment_tag}{impact_tag}</div>'''
    '''<div style="font:bold 13px Arial,sans-serif;line-height:1.35;"><a href="{link}" target="_blank" style="color:#eaecef;text-decoration:underline;text-decoration-color:#3c434d;">{headline}</a></div>'''
    '''<div style="font:11px/1.6 Arial,sans-serif;padding-top:3px;color:#848e9c;"><span style="color:#4ea1ff;font-weight:bold;white-space:nowrap;">{source} &rarr;</span> · {move}</div>'''
    '''<div style="font:11px/1.6 Arial,sans-serif;"><span style="color:#5e6673;">Since:</span> {since_words}</div></td></tr>''',
"OTHER_MORE": '''<tr><td colspan="2" style="padding:10px 0 2px;font:11px Arial,sans-serif;color:#848e9c;border-top:1px solid #1e2329;">+ {n} more lower-impact {stories} today</td></tr>''',
"WORD": '''<b style="color:{color};white-space:nowrap;">{word}</b>''',
}

SHELL = (R.HEAD.replace("<title>Oil Hourly Brief</title>", "<title>Oil Daily Wrap</title>")
         .replace("background:#05070a", "background:#0b0e11").replace('bgcolor="#05070a"', 'bgcolor="#0b0e11"')
         .replace('<td align="center" style="padding:16px 8px;">', '<td align="center" style="padding:0;">')
         .replace("border:1px solid #1e2329;border-radius:8px;overflow:hidden;", ""))
PAGE = (SHELL
        + "{header}"
        + '  <tr><td style="padding:16px 16px 6px;">{day_card}</td></tr>\n'
        + '  <tr><td style="padding:20px 16px 4px;">{the_day_title}</td></tr>\n'
        + '  <tr><td style="padding:2px 16px 0;">{chart}</td></tr>\n'
        + '  <tr><td style="padding:14px 16px 10px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{timeline_rows}</table></td></tr>\n'
        + '  <tr><td style="padding:20px 16px 4px;">{other_title}</td></tr>\n'
        + '  <tr><td style="padding:6px 16px 10px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{other_rows}</table></td></tr>\n'
        + R.FOOT_TEMPLATE.replace("{sources}", "{footer_sources}").replace("padding:14px 20px;", "padding:14px 16px;"))


def S(_snippet, **kw):
    return SNIPPETS[_snippet].format(**kw)


# ============================================================== reads (same words as #7, day versions)
def t(s):
    return dt.datetime.fromisoformat(s)


def pkt(ts, fmt="%I:%M %p"):
    return ts.astimezone(PKT).strftime(fmt).lstrip("0")


sg = R.signed


def up_down(x, hi=0, lo=0):
    return GREEN if x > hi else RED if x < lo else GREY


def oi_read(x):
    return ("Fresh money in", GREEN) if x >= 2 else ("Money leaving", RED) if x <= -2 else ("Steady money", GREY)


def flow_read(r):
    if r > 1.10: return "Buyers chased", GREEN
    if r > 1.02: return "Buyers edged ahead", GREEN
    if r >= 0.98: return "Balanced", GREY
    if r >= 0.90: return "Sellers edged ahead", RED
    return "Sellers hit bids", RED


def since_reads(long_then, long_now, money_pct, flow):
    pts = None if long_then is None else long_now - long_then
    crowd = (("Longs added", GREEN, "Longs ↑") if pts > 0.5 else ("Longs trimmed", RED, "Longs ↓") if pts < -0.5
             else ("Steady", GREY, "Longs →")) if pts is not None else ("—", DIM, "Longs —")
    money = (("Money in", GREEN, "Money ↑") if money_pct >= 1 else ("Money out", RED, "Money ↓") if money_pct <= -1
             else ("Steady", GREY, "Money →")) if money_pct is not None else ("—", DIM, "Money —")
    fl = (("Buyers", GREEN, "Buyers") if flow > 1.02 else ("Sellers", RED, "Sellers") if flow < 0.98
          else ("Even", GREY, "Even")) if flow is not None else ("—", DIM, "Flow —")
    return crowd, money, fl


# ============================================================== hourly Binance positioning helpers
def _hrows(hourly, sym, name):
    return sorted(hourly[sym][name], key=lambda r: r["timestamp"])


def _ts(r):
    return dt.datetime.fromtimestamp(r["timestamp"] / 1000, dt.timezone.utc)


def _at(rows, when):
    hit = [r for r in rows if _ts(r) <= when]
    return hit[-1] if hit else None


def since_story(hourly, when, sym="CLUSDT"):
    ls, oi, tk = (_hrows(hourly, sym, n) for n in ("globalLongShortAccountRatio", "openInterestHist", "takerlongshortRatio"))
    a, o0 = _at(ls, when), _at(oi, when)
    hour = when.replace(minute=0, second=0, microsecond=0)
    return (float(a["longAccount"]) * 100 if a else None, float(ls[-1]["longAccount"]) * 100,
            (float(oi[-1]["sumOpenInterestValue"]) / float(o0["sumOpenInterestValue"]) - 1) * 100 if o0 else None,
            next((float(r["buySellRatio"]) for r in tk if _ts(r) == hour), None))


def price_at(series, when):
    at = [p["c"] for p in series if t(p["t"]) <= when]
    return at[-1] if at else None


def slots_of(series, n=SLOTS):
    step = max(1, len(series) // n)
    return series[::-1][::step][::-1][-n:]


# ============================================================== filler
def render(data, hourly, standins=None):
    """Fill PAGE from wrap data. `standins` (preview only) supplies horizon/region/why/source/release time
    for stories saved before those fields existed."""
    standins = standins or {}
    P, Q = data["prices"], data["positioning"]
    g, w0 = t(data["generated_utc"]), t(data["window_start_utc"])

    def story(x):
        x = {**x, **standins.get(x["link"], {})}
        if not x.get("source"):
            x["source"] = urlparse(x["link"]).netloc.replace("www.", "")
        x["at"] = t(x.get("published_utc") or x["sent_utc"])  # release time when known
        return x
    stories = [story(x) for x in data["stories"]]
    top = [story(x) for x in data["top_stories"]]
    top_keys = {(x["link"], x["sent_utc"]) for x in data["top_stories"]}

    # ---- header + day card
    gp = g.astimezone(PKT)
    header = S("HEADER", when=f"{gp:%a}, {gp.day} {gp:%b %Y} · {pkt(g)} PKT · {g:%H:%M} UTC", window_start=pkt(w0))

    def chg(x):
        ch = x["change"]
        arrow, col = ("▲", GREEN) if ch > 0 else ("▼", RED) if ch < 0 else ("■", GREY)
        return dict(arrow=arrow, chg=sg(ch), chg_pct=sg(x["change_pct"]), chg_color=col)

    def range_parts(x):
        lo, hi, op, cl = x["low"], x["high"], x["open"], x["close"]
        span = (hi - lo) or 1
        pct = lambda v: max(0.0, min(100.0, (v - lo) / span * 100))
        o, c = pct(op), pct(cl); col = GREEN if cl >= op else RED; tick = 4.0
        a, b = (o, c) if c >= o else (c, o); seg = max(b - a - tick, 0.0)
        parts = ([(a, "#3c434d"), (seg, col), (tick, YELLOW), (100 - a - seg - tick, "#3c434d")] if c >= o else
                 [(a, "#3c434d"), (tick, YELLOW), (seg, col), (100 - a - seg - tick, "#3c434d")])
        return "".join(S("RANGE_PART", w=f"{w:.1f}", bg=bg) for w, bg in parts if w > 0.05)

    cells = {}
    for p, k in (("cl", "CL"), ("bz", "BRENT")):
        pad = "12px" if p == "bz" else "8px"
        ex, bn = P[k]["exchange"], P[k]["binance"]
        cells[f"{p}_tm_cell"] = S("TM_CELL", pad=pad, close=f'{ex["close"]:.2f}', open=f'{ex["open"]:.2f}', **chg(ex))
        cells[f"{p}_range_cell"] = S("RANGE_CELL", pad=pad, range_parts=range_parts(ex), low=f'{ex["low"]:.2f}', high=f'{ex["high"]:.2f}')
        cells[f"{p}_bn_cell"] = S("BN_CELL", pad=pad, close=f'{bn["close"]:.2f}', **chg(bn))
    day_card = SNIPPETS["DAY_CARD"].format(**cells)

    # ---- moments (Binance CL)
    b = P["CL"]["binance"]; cs = b["series"]; op = b["open"]
    hi, lo = max(cs, key=lambda p: p["c"]), min(cs, key=lambda p: p["c"])
    settle = g.replace(hour=SETTLE_UTC[0], minute=SETTLE_UTC[1], second=0, microsecond=0)
    if settle > g:
        settle -= dt.timedelta(days=1)
    moments = [("OPEN", t(cs[0]["t"]), op, GREY), ("DAY HIGH", t(hi["t"]), hi["c"], GREEN), ("DAY LOW", t(lo["t"]), lo["c"], RED)]
    if t(cs[0]["t"]) <= settle <= g:
        moments.append(("NYMEX SETTLE", settle, price_at(cs, settle), YELLOW))

    # ---- chart
    pts = slots_of(cs)
    devs = [p["c"] - op for p in pts]
    W = f"{100 / SLOTS:.2f}"

    def col(up, down, half, half_dn=None):
        """up/down: lists of (height, colour) stacked away from the centre line (nearest the line first).
        half / half_dn: space above / below the line for this panel (a side with no bars gets none)."""
        half_dn = half if half_dn is None else half_dn
        u, dn = sum(h for h, _ in up), sum(h for h, _ in down)
        top = ([(half - u, None)] if half - u > 0 else []) + list(reversed(up))
        bot = list(down) + ([(half_dn - dn, None)] if half_dn - dn > 0 else [])
        line = 'style="border-bottom:1px solid #5e6673;" ' if top else 'style="border-top:1px solid #5e6673;" '
        cells = [S("FILL", h=h, color=c, line="") if c else S("SP", h=h, line="") for h, c in top]
        bcells = [S("FILL", h=h, color=c, line="") if c else S("SP", h=h, line="") for h, c in bot]
        # the 1px centre line: bottom border of the last cell above it (or top border of the first below)
        if top:
            cells[-1] = cells[-1].replace(' height=', ' ' + line + 'height=', 1)
        elif bcells:
            bcells[0] = bcells[0].replace(' height=', ' ' + line + 'height=', 1)
        return S("COL", w=W, rows="".join(cells) + "".join(bcells))

    def halves(vals, full):
        """Pixels above / below the line: the side the bars reach, scaled to the biggest move (0 if never used)."""
        big = max([abs(v) for v in vals if v is not None] + [1e-9])
        up = max([v for v in vals if v is not None and v > 0] + [0]) / big * full
        dn = -min([v for v in vals if v is not None and v < 0] + [0]) / big * full
        return big, round(up) if up else 0, round(dn) if dn else 0
    big, pu, pd = halves(devs, PRICE_HALF)
    pu, pd = (max(pu, 1) if any(v > 0 for v in devs) else 0), (max(pd, 1) if any(v < 0 for v in devs) else 0)
    price_cols = "".join(col([(max(1, round(v / big * PRICE_HALF)), GREEN)] if v > 0 else [],
                             [(max(1, round(-v / big * PRICE_HALF)), RED)] if v < 0 else [], pu, pd) for v in devs)
    bounds = [(t(p["t"]), t(pts[i + 1]["t"]) if i + 1 < len(pts) else t(p["t"]) + dt.timedelta(minutes=30)) for i, p in enumerate(pts)]
    bounds[0] = (min(bounds[0][0], t(cs[0]["t"])), bounds[0][1])
    marks = [(x["at"], "▲", R.SENT[x["sentiment"]][2]) for x in top] + [(w, "■", c) for _, w, _, c in moments]
    mark_cells, label_cells, last = [], [], -99
    for i, (s0, s1) in enumerate(bounds):
        hit = sorted([m for m in marks if s0 <= m[0] < s1], key=lambda m: m[1] != "▲")
        mark_cells.append(S("MARK_CELL", mark=S("MARK", color=hit[0][2], shape=hit[0][1]) if hit else "&nbsp;"))
        lab = ""
        if hit and i - last >= 3:
            lab = pkt(hit[0][0], "%I:%M").lstrip("0"); last = i
        label_cells.append(S("MARK_LABEL_CELL", label=lab or "&nbsp;"))
    lean = {"Bullish": 1, "Slightly Bullish": 1, "Neutral": 0, "Slightly Bearish": -1, "Bearish": -1}
    slot_stories = [[x for x in stories if s0 <= x["at"] < s1] for s0, s1 in bounds]
    n_up = max([sum(1 for x in sl if lean[x["sentiment"]] >= 0) for sl in slot_stories] + [0])
    n_dn = max([sum(1 for x in sl if lean[x["sentiment"]] < 0) for sl in slot_stories] + [0])
    NH, NH_DN = max(n_up, 1) * (BLOCK + BLOCK_GAP), n_dn * (BLOCK + BLOCK_GAP)

    def blocks(items, gap_first):
        """Each story = a 5px block with a 1px gap, matching the original stacks exactly."""
        out = []
        for x in items:
            pair = [(BLOCK, R.SENT[x["sentiment"]][2]), (BLOCK_GAP, None)]
            out += pair[::-1] if gap_first else pair
        return out
    news_cols = ""
    for sl in slot_stories:
        up = sorted([x for x in sl if lean[x["sentiment"]] >= 0], key=lambda x: (lean[x["sentiment"]], x["sentiment"] == "Bullish"))
        dn = sorted([x for x in sl if lean[x["sentiment"]] < 0], key=lambda x: x["sentiment"] == "Bearish")
        # up stack is listed nearest-the-line first: original drew top->bottom = reversed(up) with each block followed by its gap
        news_cols += col(blocks(up, True), blocks(dn, False), NH, NH_DN)
    ls = _hrows(hourly, "CLUSDT", "globalLongShortAccountRatio")
    first, lastv = float(ls[0]["longAccount"]) * 100, float(ls[-1]["longAccount"]) * 100
    cvals = [(lambda r: None if r is None else float(r["longAccount"]) * 100 - first)(_at(ls, s0)) for s0, _ in bounds]
    shown = [v if v is not None and abs(v) > 0.05 else 0 for v in cvals]
    bigc, cu, cd = halves(shown + [0.1], CROWD_HALF)
    cu, cd = (max(cu, 1) if any(v > 0 for v in shown) else 0), (max(cd, 1) if any(v < 0 for v in shown) else 0)
    crowd_cols = "".join(col([(max(1, round(v / bigc * CROWD_HALF)), GREEN)] if v > 0 else [],
                             [(max(1, round(-v / bigc * CROWD_HALF)), RED)] if v < 0 else [], cu, cd) for v in shown)
    tl = data["sentiment_tally"]
    def merge_empty(cells_list, empty_marker, make_empty):
        out, run = [], 0
        for c in cells_list:
            if c == empty_marker:
                run += 1; continue
            if run:
                out.append(make_empty(run)); run = 0
            out.append(c)
        if run:
            out.append(make_empty(run))
        return "".join(out)
    e_mark = S("MARK_CELL", mark="&nbsp;"); e_lab = S("MARK_LABEL_CELL", label="&nbsp;"); e_ax = S("AXIS_CELL", label="&nbsp;")
    span = lambda cell: (lambda n: cell if n == 1 else cell.replace("<td ", f'<td colspan="{n}" ', 1))
    mark_cells = merge_empty(mark_cells, e_mark, span(e_mark))
    label_cells = merge_empty(label_cells, e_lab, span(e_lab))
    axis_list = [S("AXIS_CELL", label=pkt(s0, "%I%p").lstrip("0").lower() if i % 6 == 0 else "&nbsp;") for i, (s0, _) in enumerate(bounds)]
    axis_cells = merge_empty(axis_list, e_ax, span(e_ax))
    chart = S("CHART", slots=len(pts), open=f"{op:.2f}", high_vs_open=sg(hi["c"] - op), low_vs_open=sg(lo["c"] - op),
              price_cols=price_cols, mark_cells=mark_cells, mark_label_cells=label_cells,
              n_bull=tl["Bullish"] + tl["Slightly Bullish"], n_neutral=tl["Neutral"], n_bear=tl["Bearish"] + tl["Slightly Bearish"],
              news_cols=news_cols, long_start=f"{first:.1f}", long_end=f"{lastv:.1f}", crowd_cols=crowd_cols, axis_cells=axis_cells)

    # ---- timeline
    def move_html(at_px):
        if at_px is None:
            return SNIPPETS["MOVE_MISSING"]
        mv = round(b["close"] - at_px, 2)
        return S("MOVE", color=up_down(mv), move=sg(mv))

    def tags(x):
        _, sbg, sfg, _ = R.SENT[x["sentiment"]]; _, ibg, ifg = R.IMPACT[x["impact"]]
        return R.tag(x["sentiment"], sbg, sfg), R.tag(x["impact"], ibg, ifg)

    events = [(w, "moment", (name, px, col)) for name, w, px, col in moments] + [(x["at"], "story", x) for x in top]
    events.sort(key=lambda e: e[0])
    rows = []
    for k_, (when, kind, x) in enumerate(events):
        if kind == "moment":
            name, px, col = x
            rows.append(S("TL_ROW", pad="8px", time=pkt(when), rail="border-left:2px solid #2b3139;",
                          left_price=S("LEFT_PRICE", color=YELLOW, price=f"{px:.2f}"), dot=S("DOT", color=col, shape="■"),
                          content=S("MOMENT_CONTENT", color=col if col != GREY else "#b7bdc6", name=name)))
            continue
        at_px = (x.get("prices") or {}).get("cl_bn") or price_at(cs, when)
        lt, ln, mp, fl = since_story(hourly, when)
        c, m, f = since_reads(lt, ln, mp, fl)
        tcells = [("CROWD", c, f"{lt:.1f}&rarr;{ln:.1f}%" if lt is not None else "—"),
                  ("MONEY", m, f"{sg(mp, 1)}%" if mp is not None else "—"),
                  ("FLOW 1H", f, f"{fl:.2f}" if fl is not None else "—")]
        traders = "".join(S("TRADERS_CELL", pad_left="8px" if i == 0 else "6px", divider="" if i == 2 else "border-right:1px solid #2b3139;",
                            label=lab, color=r[1], read=r[0], number=num) for i, (lab, r, num) in enumerate(tcells))
        st, it = tags(x)
        rows.append(S("TL_ROW", pad="10px", time=pkt(when), rail="border-left:2px solid #2b3139;",
                      left_price=S("LEFT_PRICE", color="#b7bdc6", price=f"{at_px:.2f}") if at_px is not None else "",
                      dot=S("DOT", color=R.SENT[x["sentiment"]][2], shape="▲"),
                      content=S("STORY_CONTENT", sentiment_tag=st, impact_tag=it, link=E(x["link"], quote=True), headline=E(x["headline"]),
                                why=E(x.get("why", "")), horizon_region=E(" · ".join(v for v in (x.get("horizon"), x.get("region")) if v)),
                                source=E(x["source"]), move=move_html(at_px), traders_cells=traders)))
    q = Q["CLUSDT"]; was = q["long_short_ratio_24h_ago"] / (1 + q["long_short_ratio_24h_ago"]) * 100; pts_ = q["long_pct"] - was
    cw, cc = (("Longs added", GREEN) if pts_ > 0.5 else ("Longs trimmed", RED) if pts_ < -0.5 else ("Crowd unchanged", GREY))
    ow, oc = oi_read(q["oi_change_pct_24h"]); fw, fc = flow_read(q["taker_buy_sell_24h"])
    rows.append(S("TL_ROW", pad="10px", time=pkt(g), rail="", left_price="", dot=S("DOT", color="#eaecef", shape="●"),
                  content=S("EOD_CONTENT", crowd_color=cc, crowd_read=cw, long_was=f"{was:.0f}", long_now=f'{q["long_pct"]:.0f}',
                            money_color=oc, money_read=ow, money_pct=sg(q["oi_change_pct_24h"]), flow_color=fc, flow_read=fw,
                            flow=f'{q["taker_buy_sell_24h"]:.2f}')))

    # ---- other news
    rest_all = [x for x in stories if (x["link"], x["sent_utc"]) not in top_keys]
    rank = {"High": 3, "Medium": 2, "Low": 1}
    keep = sorted(rest_all, key=lambda x: (rank.get(x["impact"], 0), x["at"]), reverse=True)[:MAX_OTHER]  # most important first
    rest = sorted(keep, key=lambda x: x["at"])  # shown in time order
    hidden = len(rest_all) - len(rest)
    other = []
    for i, x in enumerate(rest):
        at_px = (x.get("prices") or {}).get("cl_bn") or price_at(cs, x["at"])
        c, m, f = since_reads(*since_story(hourly, x["at"]))
        st, it = tags(x)
        other.append(S("OTHER_ROW", border="" if i == len(rest) - 1 else LINE, time=pkt(x["at"]),
                       left_price=S("LEFT_PRICE", color="#b7bdc6", price=f"{at_px:.2f}") if at_px is not None else "",
                       sentiment_tag=st, impact_tag=it, link=E(x["link"], quote=True), headline=E(x["headline"]),
                       source=E(x["source"]), move=move_html(at_px),
                       since_words=" · ".join(S("WORD", color=r[1], word=r[2]) for r in (c, m, f))))

    page = PAGE.format(
        header=header, day_card=day_card,
        the_day_title=R.section_title("THE DAY", '<b style="color:#eaecef;">%d</b> top stories of %d' % (len(top), data["story_count"])),
        chart=chart, timeline_rows="".join(rows),
        other_title=R.section_title("OTHER NEWS", '<b style="color:#eaecef;">%d</b> more · in time order' % len(rest_all)),
        other_rows="".join(other) + (S("OTHER_MORE", n=hidden, stories="story" if hidden == 1 else "stories") if hidden else ""),
        footer_sources=", ".join(sorted({x["source"] for x in top})) + ", Hyperliquid (traditional market), Binance")
    return R.email_safe(page)


# ============================================================== placeholder reference
FIELDS = """
PAGE placeholders (one each)
  {header}            HEADER snippet. {when} = generated_utc as "Fri, 27 Nov 2026 · 2:47 AM PKT · 21:47 UTC"; {window_start} = window_start_utc in PKT.
  {day_card}          DAY_CARD snippet (below).
  {the_day_title}     render_email.section_title("THE DAY", "<b>{len(top_stories)}</b> top stories of {story_count}").
  {chart}             CHART snippet (below).
  {timeline_rows}     TL_ROW per event, sorted by time: one per price moment + one per top story, then the end-of-day row last.
  {other_title}       section_title("OTHER NEWS", "<b>{n}</b> more · in time order"), n = stories not in top_stories.
  {other_rows}        OTHER_ROW per remaining story, by release time. {border} = 1px #1e2329 bottom line, "" on the last row.
  {footer_sources}    sorted sources of the top stories + ", Hyperliquid (traditional market), Binance".

DAY CARD (prefix cl_ = prices.CL, bz_ = prices.BRENT; {pad} = 8px for CL, 12px for Brent)
  TM_CELL   {close} exchange.close 2dp · {open} exchange.open 2dp · {arrow}{chg}{chg_pct}{chg_color} from exchange.change / change_pct:
            ▲ green >0, ▼ red <0, ■ grey 0; signed 2dp with U+2212 minus.
  RANGE_CELL {low}/{high} exchange.low/high 2dp, Low at the left end, High at the right. {range_parts} = RANGE_PART cells across 100%:
            track #3c434d from low to the open-or-close (whichever is lower), coloured run (green if close>=open, red if lower)
            from open to close, a 3% white tick at the close, track to high. Widths = (price-low)/(high-low)*100.
  BN_CELL   binance.close / change / change_pct, same rules as TM_CELL.

THE DAY CHART (Binance CL only: prices.CL.binance; 24 hourly slots from its 15-min series, last close in each slot)
  {open} binance.open · {high_vs_open} binance.high-open · {low_vs_open} binance.low-open (signed 2dp).
  {price_cols}  DIV_COL per slot, half=36: BAR up (green) when slot close > open, BAR down (red) when < open;
                px = max(1, round(|close-open| / max|close-open| * 36)).
  {mark_cells}  MARK_CELL per slot: MARK ▲ in the sentiment colour if a top story was RELEASED in the slot (wins over ■),
                else ■ for a price moment (OPEN grey, DAY HIGH green, DAY LOW red, NYMEX SETTLE yellow #f0b90b), else &nbsp;.
  {mark_label_cells} MARK_LABEL_CELL per slot: the mark's PKT time "1:03", skipped if within 3 slots of the previous label.
  {news_cols}   DIV_COL per slot, half = (most stories in any slot, up or down) * 6px. Up: BLOCKS of stories released in the slot that lean
                bullish or neutral (Bullish/Slightly Bullish green shades, Neutral grey), down: Slightly Bearish/Bearish. One BLOCK per story,
                colour = render_email.SENT[sentiment][2].
  {n_bull}/{n_neutral}/{n_bear} from sentiment_tally (Bullish+Slightly Bullish / Neutral / Slightly Bearish+Bearish).
  {crowd_cols}  DIV_COL per slot, half=22: % accounts long (hourly globalLongShortAccountRatio.longAccount*100, latest reading at or before
                the slot) minus the day's first reading; BAR up green if > +0.05, down red if < -0.05; scaled to the largest change.
  {long_start}/{long_end} first and last hourly % long, 1dp.
  {axis_cells}  AXIS_CELL per slot: PKT hour like "3am" every 6th slot, else &nbsp; (runs of empty cells merged with colspan).

TIMELINE (TL_ROW: {time} PKT "1:03 PM", {pad} 8px moments / 10px stories, {rail} 2px #2b3139 left line, "" on the end-of-day row)
  Price moment: {left_price} LEFT_PRICE yellow #f0b90b; {dot} DOT ■ in its colour; {content} MOMENT_CONTENT name.
                OPEN = first slot / binance.open; DAY HIGH/LOW = max/min of the series and its time; NYMEX SETTLE = 19:30 UTC
                (18:30 UTC under US daylight saving), price at or before it. Times and prices are Binance CL.
  Top story:    placed at its RELEASE time = story.published_utc (fall back to sent_utc only if missing).
                {left_price} LEFT_PRICE grey #b7bdc6 = story.prices.cl_bn (Binance CL when it was released; else series price at that time);
                {dot} DOT ▲ sentiment colour; STORY_CONTENT: {sentiment_tag}/{impact_tag} = render_email.tag(); {link}; {headline}; {why};
                {horizon_region} "Short-term · Middle East"; {source}; {move} = MOVE "CL since then" + signed(binance.close - cl_bn),
                green/red/grey, or MOVE_MISSING "CL since: —" when cl_bn is missing.
                {traders_cells} = 3 TRADERS_CELL (CROWD | MONEY | FLOW 1H), CLUSDT hourly rows:
                  CROWD   % long at the story hour -> now ("64.1→62.5%"): "Longs added" >+0.5 pts green, "Longs trimmed" <-0.5 red, else "Steady".
                  MONEY   open-interest value now vs at the story hour, % 1dp: >=+1 "Money in" green, <=-1 "Money out" red, else "Steady".
                  FLOW 1H taker buySellRatio for the hour the story came out, 2dp: >1.02 "Buyers" green, <0.98 "Sellers" red, else "Even".
                  Missing data: read "—" in #5e6673, number "—".
  End of day:   last row, {time} = generated time, DOT ● white, EOD_CONTENT from positioning.CLUSDT:
                {long_was} = ratio_24h_ago/(1+ratio_24h_ago)*100, {long_now} = long_pct (whole numbers); crowd read as CROWD above (vs yesterday);
                {money_read} oi_change_pct_24h >=+2 "Fresh money in" / <=-2 "Money leaving" / "Steady money"; {money_pct} signed 2dp;
                {flow_read} taker_buy_sell_24h: >1.10 "Buyers chased", >1.02 "Buyers edged ahead", >=0.98 "Balanced",
                >=0.90 "Sellers edged ahead", else "Sellers hit bids"; {flow} 2dp.

OTHER NEWS (OTHER_ROW, same rules as top stories, compact)
  At most MAX_OTHER (20) rows: the most important by impact (then newest), shown in time order; if more, OTHER_MORE "+{n} more
  lower-impact {stories} today" ({stories} = "story" when n is 1). The title count is the full number. Source names are plain blue text; only the headline is a link.
  {time} release time PKT · {left_price} Binance CL at release (grey) · tags · {headline} linked · {source} · {move} as above ·
  {since_words} = three WORD items: "Longs ↑/↓/→", "Money ↑/↓/→", "Buyers/Sellers/Even" with the same thresholds and colours.

DATA THE WRAP NEEDS THAT IT DOES NOT HAVE YET (parent session)
  1. story.published_utc: fetch_data.read_feed already reads pubDate; carry it into analysis.json stories and state.py's keep list.
  2. Hourly Binance positioning for CLUSDT (and BZUSDT if wanted): fetch_data.positioning() already pulls 25 hourly rows of
     globalLongShortAccountRatio, openInterestHist and takerlongshortRatio; wrap_data should keep all rows (shape: sample-positioning-hourly.json).
  3. story.prices.cl_bn is already saved by state.py for new stories; migrated stories have none (the filler falls back to the series).
"""


def missing(data):
    """The wrap needs a full day of Binance CL data; name whatever is missing instead of failing halfway."""
    out = []
    for k in ("CL", "BRENT"):
        for side in ("exchange", "binance"):
            if not (data.get("prices", {}).get(k) or {}).get(side):
                out.append(f"prices.{k}.{side}")
    if "CLUSDT" not in data.get("positioning", {}):
        out.append("positioning.CLUSDT")
    hourly = data.get("positioning_hourly", {}).get("CLUSDT", {})
    for name in ("globalLongShortAccountRatio", "openInterestHist", "takerlongshortRatio"):
        if not hourly.get(name):
            out.append(f"positioning_hourly.CLUSDT.{name}")
    return out


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    gaps = missing(data)
    if gaps:
        sys.exit("missing data, fetch again: " + ", ".join(gaps))
    sys.stdout.write(render(data, data["positioning_hourly"]))


if __name__ == "__main__":
    main()
