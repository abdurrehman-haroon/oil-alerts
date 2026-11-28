# Oil Hourly Brief: routine instructions

You are running as a scheduled cloud routine. Produce one Oil Hourly Brief email and send it. Work from this
repository's root. Never change `render_email.py`'s design or `email-template-dark.html`.

## 1. Fetch data

```bash
python3 fetch_data.py > /tmp/data.json
```

This collects CL/Brent prices (Hyperliquid + Binance), Binance funding, the news published since the previous scheduled
run (full article text where available) and calendar events for the next 24 hours. Read `/tmp/data.json`.
Anything that failed is listed under `errors`; carry on with what you have and never invent a value.

## 2. Build the stories

From `news`, keep only items that are real news or analysis relevant to the crude oil price (CL first, then
Brent). Drop promos, product pages, newsletters, pure natural-gas or unrelated stories, and anything whose text is
site navigation rather than an article.

Don't repeat earlier emails. Skip every item marked `"already_sent": true`, and skip any item that covers the same
event as a headline in `recently_sent` (stories emailed in the last 24 hours), even from a different outlet. The
only exception is a genuinely new development on that event (a new number, decision or price move); then write it
as an update, e.g. headline "UPDATE: …", and say what changed.

Group items that cover the same event into one story. For each story pick the best source: one with `"access": "full"`
if any, otherwise the earliest. Cap the email at 15 stories, keeping the most important.

Prefer stories you can actually read. Stories with a `"access": "full"` source come first; a headline-only story
(every source `"access": "headline"`) is thin, so keep at most 3 of them, choosing the most important. A
headline-only story with `High` impact doesn't count toward that limit, so breaking news is never dropped.

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
| `published_utc` | the best source's `published_utc`, copied as is (null if it has none) |
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
{"stories": [ ... ], "extra_events": [ ... ], "dropped": [ ... ]}
```

`dropped` records why each `news` item you did NOT turn into a story was left out, for later analysis:
`{"link": "<the item's link>", "reason": "<one of: not_oil, grouped, already_sent, repeat_24h, headline_cap, over_cap, low_value>"}`.
`grouped` = merged into another story; `repeat_24h` = same event as a `recently_sent` headline; `headline_cap` = over
the 3 headline-only limit; `over_cap` = over the 15-story limit; `low_value` = relevant but too minor. One entry per
left-out item; items that became stories are not listed.

Order stories newest first; the renderer sorts by impact. If there are no relevant stories, use an empty list. The
email still goes out with prices.

## 3. Render

```bash
python3 render_email.py /tmp/data.json /tmp/analysis.json > /tmp/email.html
```

If it exits with a validation error, fix `/tmp/analysis.json` and run it again.

## 4. Send

Write the plain-text fallback to `/tmp/email.txt`: one line with CL and Brent prices, then each story headline on its
own line. Then send the rendered file with the script. Do NOT open, read, retype or edit `/tmp/email.html`:

```bash
python3 send_email.py /tmp/email.html "Oil Hourly Brief · CL <Binance CL price> · <time PKT from data.json generated_pkt>" /tmp/email.txt
```

e.g. subject `Oil Hourly Brief · CL 90.08 · 7:12 PM PKT`. The script reads the sender, credentials and recipients from
environment variables. They are kept out of this repository on purpose.

If the script exits with an error, do not try another way to send. Skip step 5 and put the script's error in the
final report.

## 5. Remember what was sent

After a successful send, record this run's stories, prices and positioning so later runs don't repeat them and the
daily wrap has the day's history:

```bash
python3 state.py save /tmp/analysis.json /tmp/data.json
```

This appends to `data/stories/` and `data/snapshots/` and pushes one commit to `main`; it is the only push allowed.
If it fails, mention it in the report; the email has already gone.

## 6. Finish

End with a two-line report: how many stories were sent, how many were skipped as already sent, and any `errors`
from the fetch.
