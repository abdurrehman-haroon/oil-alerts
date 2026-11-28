# Oil Daily Wrap: routine instructions

You are running as a scheduled cloud routine, once per trading day just after NYMEX settlement. Send one Daily Wrap
email covering the last 24 hours. Everything is scripted: you write nothing yourself. Work from this repository's
root. Never change `render_wrap.py`, `render_email.py` or any file in the repository.

## 1. Collect the day

```bash
python3 wrap_data.py > /tmp/wrap.json
```

## 2. Render

```bash
python3 render_wrap.py /tmp/wrap.json > /tmp/wrap.html
```

If it exits with "missing data, fetch again", wait about a minute (`sleep 60`) and repeat steps 1 and 2 once. If it
still fails, don't send anything: report the error and stop.

## 3. Send

Write `/tmp/wrap.txt`: one line `Oil Daily Wrap · CL <prices.CL.exchange.close> (<prices.CL.exchange.change_pct>%) ·
Brent <prices.BRENT.exchange.close> (<change_pct>%)`, then the headline of each `top_stories` item on its own line.
Then send the rendered file. Do NOT open, read, retype or edit `/tmp/wrap.html`:

```bash
python3 send_email.py /tmp/wrap.html "Oil Daily Wrap · CL <prices.CL.exchange.close> <signed change_pct>% · <date PKT, e.g. 28 Nov>" /tmp/wrap.txt
```

e.g. subject `Oil Daily Wrap · CL 84.78 +0.83% · 27 Nov`. If the script exits with an error, don't try another way
to send; report the error.

## 4. Save the day

After a successful send, append the day's numbers (prices, settle, positioning, sentiment, top stories) to the history:

```bash
python3 state.py save-wrap /tmp/wrap.json
```

This pushes one commit to `main`; it is the only push allowed. If it fails, mention it in the report.

## 5. Finish

End with a two-line report: CL and Brent day change, how many stories were in the wrap, and any `errors` from
`/tmp/wrap.json`. Do not commit or push anything yourself.
