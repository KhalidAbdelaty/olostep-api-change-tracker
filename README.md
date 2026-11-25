# Demo Payments API change tracker

This project watches one fictional documentation page, the Demo Payments API reference, with an Olostep Monitor. When the monitor calls back, a FastAPI service looks the run up through the authenticated Olostep Monitors API, checks whether the required parameters of `POST /payments` changed, and opens one GitHub Issue for a developer to review.

The Issue says "potential breaking documentation change, pending review". A docs edit does not prove the live API changed.

## What is in the repository

| Path | What it does |
| --- | --- |
| `docs/index.html` | The page GitHub Pages publishes and the monitor watches |
| `stages/` | The three versions of that page: baseline, cosmetic edit, `customer_id` renamed to `account_id` |
| `app/main.py` | FastAPI receiver. Stores the callback in SQLite and returns `202` |
| `app/worker.py` | Background worker: verify, classify, open the Issue |
| `app/verify.py` | Matches a callback to an event from `GET /v1/monitors/{id}/events` |
| `app/classify.py` | Reads the required parameters from the snapshot and compares them |
| `app/store.py` | SQLite tables for callbacks, verified runs, and contracts |
| `app/github_client.py` | Creates the Issue and finds it again by a hidden marker |
| `scripts/` | Create the monitor, attach the webhook, list events, check the live page, switch stages |
| `tests/` | Replay, unmatched callbacks, and injected GitHub failures, all with test doubles |

## Requirements

- Python 3.11 or later (tested with 3.11.9)
- An Olostep API key
- A public GitHub repository with Pages (branch `main`, folder `/docs`) and Issues turned on
- A fine-grained personal access token limited to that repository, with **Issues** set to **Read and write**
- A public HTTPS URL for the receiver, for example `ngrok http 8000`

```bash
pip install -r requirements.txt
```

## Settings

Set the secrets in your own shell. Never put real values in a file you commit. `.env.example` lists every variable.

```bash
export OLOSTEP_API_KEY=...        # from the Olostep dashboard
export GITHUB_PAT=...             # fine-grained token, Issues: Read and write
export GITHUB_REPO=your-user/olostep-api-change-tracker
export DOCS_URL=https://your-user.github.io/olostep-api-change-tracker/
export WEBHOOK_PATH_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
```

On Windows PowerShell, use `$env:OLOSTEP_API_KEY = "..."` and so on.

## Run the experiment

Each stage needs its own completed monitor run. The shortest schedule is every 10 minutes, and GitHub Pages can take up to 10 minutes to publish, so plan for about an hour.

1. Publish the baseline and wait until the live page shows it:

   ```bash
   python scripts/publish_stage.py 1
   git add docs/index.html && git commit -m "Publish baseline docs" && git push
   python scripts/check_live_page.py
   ```

2. Start the receiver and a tunnel in two terminals:

   ```bash
   uvicorn app.main:app --port 8000
   ngrok http 8000
   ```

3. Create the monitor, wait for `active`, then attach the webhook:

   ```bash
   python scripts/create_monitor.py
   export OLOSTEP_MONITOR_ID=monitor_...
   python scripts/show_monitor.py --wait
   python scripts/set_webhook.py https://<your-tunnel-host>
   ```

   Restart `uvicorn` after you export `OLOSTEP_MONITOR_ID` so the receiver knows which monitor to accept.

   In my run, the first snapshot was taken the moment the monitor became `active`, before the first cron slot. If the webhook was not attached in time, run the reconcile script below to pick that run up.

4. Check the events and what the receiver recorded:

   ```bash
   python scripts/list_events.py
   python scripts/status.py
   python scripts/reconcile.py
   ```

5. Publish stage 2 (cosmetic), wait for a completed run, then publish stage 3 (`account_id`) and wait again. Check `python scripts/check_live_page.py` before each wait.

6. Replay the change callback. No second Issue should appear:

   ```bash
   python scripts/replay.py <delivery-id>
   ```

7. Pause the monitor when you finish so it stops using requests:

   ```bash
   python scripts/pause_monitor.py
   ```

## Tests

```bash
python -m pytest -q
```

The tests never call Olostep or GitHub. They use `httpx.MockTransport` doubles in `tests/fakes.py` to inject a GitHub `503`, a read timeout after GitHub already stored the Issue, a crash between the create call and the local write, and a `410` for disabled Issues.

## What the November 25, 2026 run showed

- The webhook fired after every completed run, including the first snapshot and runs with no change, even with `notification.events` left empty.
- The callback body carried `monitor_id`, `run_id`, `changed`, `is_first_snapshot`, `summary`, `content`, and `markdown_differences`. Olostep does not document this body, so the code reads only the two IDs from it.
- The `snapshot_url` in the events list returned `403 AccessDenied` for every run. The worker reads the page from `GET /v1/monitors/{id}/runs/{run_id}` instead, using the node output that holds the fresh scrape (`markdown`), not the stored baseline (`content`).
- The cosmetic edit came back `changed: false`. The `customer_id` to `account_id` edit came back `changed: true` and opened one Issue.

## Limits

- Olostep lists signed webhook payloads as coming soon, so the receiver trusts nothing in the callback body. It checks the path token, refuses other monitor IDs, and only acts on a run it finds through the authenticated events API.
- The snapshot URL Olostep returns is pre-signed and short-lived. The worker downloads it right away and never logs or stores it.
- If the process dies after GitHub accepts the Issue and before SQLite records it, the row stays `issue_creating`. The next attempt searches the repository for the hidden marker before it posts again.
