# Oil Hourly Brief

Cloud routine that emails an hourly crude oil brief (CL focus, plus Brent): prices from CNBC and Binance, Binance funding, summarized news with sentiment, impact and horizon, and the next 24 hours of events.

- `fetch_data.py`: collects prices, funding, news and calendar events into one JSON file (standard library only)
- `render_email.py`: turns that data plus Claude's analysis into the HTML email
- `email-template-dark.html`: the approved design reference
- `ROUTINE.md`: step-by-step instructions the routine follows each run
