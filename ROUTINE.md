# Oil Hourly Brief: routine instructions

You are running as a scheduled cloud routine. Produce one Oil Hourly Brief email and send it. Work from this
repository's root. Never change `render_email.py`'s design or `email-template-dark.html`.

## 1. Fetch data

```bash
python3 fetch_data.py > /tmp/data.json
```

This collects CL/Brent prices (CNBC + Binance), Binance funding, the news published since the previous scheduled
run (full article text where available) and calendar events for the next 24 hours. Read `/tmp/data.json`.
Anything that failed is listed under `errors`; carry on with what you have and never invent a value.

## 2. Build the stories

From `news`, keep only items that are real news or analysis relevant to the crude oil price (CL first, then
Brent). Drop promos, product pages, newsletters, pure natural-gas or unrelated stories, and anything whose text is
site navigation rather than an article.

Group items that cover the same event into one story. For each story pick the best source: one with `"access": "full"`
if any, otherwise the earliest. Cap the email at 15 stories, keeping the most important.

For each story write:

| field | rule |
|---|---|
| `headline` | the best source's title, cleaned of the trailing " - Outlet" suffix |
| `link` | the best source's link |
| `source` | the best source's `source` value |
| `sources_count` | number of distinct sources grouped into the story |
| `headline_only` | `true` only if every source in the story has `"access": "headline"` |
| `summary` | full text available: 4–6 sentences (80–120 words) covering what happened, key numbers (barrels, %, prices), who said it or why, market reaction or context, and what to watch next. Headline only: 1–2 sentences from the title and feed summary, never more. Plain text, your own words, no quotes longer than a few words. |
| `why` | one short line on how it affects CL specifically |
| `sentiment` | effect on CL price: `Bullish` (clear, strong upward pressure), `Slightly Bullish`, `Neutral`, `Slightly Bearish`, `Bearish` (clear, strong downward pressure) |
| `impact` | how much it could move CL: `High` (>2%), `Medium` (0.5–2%), `Low` (<0.5%) |
| `horizon` | when the effect lands: `Short-term` (hours–days), `Medium-term` (weeks–3 months), `Long-term` (6+ months) |
| `region` | one short tag: US, Middle East, Russia, China, Europe, Japan, OPEC+, Asia, Africa, Latin America, Global |

Guidance for sentiment and impact:
- Supply cuts, outages, sanctions, conflict near producers or shipping lanes, inventory draws, strong demand data → bullish.
- Output increases, inventory builds, weak demand or macro data, ceasefires and de-escalation, stronger US dollar → bearish.
- Use `High` sparingly: OPEC+ decisions, large supply disruptions, major sanctions, big EIA surprises, Fed shocks.
- Base it on the article content, not the headline tone. If unsure, choose the milder level.

Also add `extra_events` for any scheduled event in the next 24 hours that the news mentions but the calendar may
miss (for example an OPEC+ meeting): `{"time_utc": "...Z", "title": "...", "short": "OPEC+"}`. Only include events
with a known time.

Write the result to `/tmp/analysis.json`:

```json
{"stories": [ ... ], "extra_events": [ ... ]}
```

Order stories newest first; the renderer sorts by impact. If there are no relevant stories, use an empty list. The
email still goes out with prices.

## 3. Render

```bash
python3 render_email.py /tmp/data.json /tmp/analysis.json > /tmp/email.html
```

If it exits with a validation error, fix `/tmp/analysis.json` and run it again.

## 4. Send

Send ONE email with the Gmail connector's send tool:
- to: the recipient addresses listed in the routine's prompt (all of them in To). They are kept out of this repository on purpose.
- subject: `Oil Hourly Brief · CL <binance or CNBC CL price> · <time PKT from data.json generated_pkt>`,
  e.g. `Oil Hourly Brief · CL 90.08 · 7:12 PM PKT`
- htmlBody: the full, unmodified contents of `/tmp/email.html`
- body (plain-text fallback): one line with CL and Brent prices, then each story headline on its own line

Send exactly one email per run, even if a step failed, so the recipients know the routine is alive. If rendering
failed completely, send a plain-text email with the prices and headlines you have.

## 5. Finish

End with a two-line report: how many stories were sent and any `errors` from the fetch.
