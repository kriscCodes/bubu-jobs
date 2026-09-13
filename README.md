# bubu-jobs

A small Python 3.11+ job-alert pipeline. Its only source is the [Jobright Product Management new-grad README](https://github.com/jobright-ai/2026-Product-Management-New-Grad/blob/master/README.md). It prints newly discovered relevant jobs and persists their identities in JSON. The scraper needs no third-party packages. Optional Twilio SMS uses four environment settings; no database, LLM, or application automation is included.

## Setup and local use

Use Python 3.11+ on macOS or Linux (local locking uses standard-library `fcntl`). Run these commands from this project's root:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.main
```

Options:

```sh
python -m src.main --verbose
python -m src.main --force
python -m src.main --state /tmp/bubu-test/seen_jobs.json
```

`--force` bypasses the conditional fetch, but still deduplicates jobs. `--state` selects an independent state file. The default state path is relative to the project, not the caller's working directory. Run as a module (`python -m src.main`). Logs go to stderr; counts and new job details go to stdout. Failures return a nonzero exit code.

**Delivered state:** the included JSON contains previously discovered matches and is updated by GitHub Actions. To experience a fresh first run, use a separate `--state` path. To intentionally forget history, back up and delete `data/seen_jobs.json`; the next run will report every currently relevant listing as new.

## Pipeline

1. Load state while holding an exclusive local lock.
2. Fetch the raw README with a 30-second network timeout and at most three attempts. Retry transient connection errors and HTTP 429/500/502/503/504 with bounded backoff; honor numeric Retry-After up to 60 seconds.
3. Send `If-None-Match` when a saved ETag is available. HTTP 304 skips downloading and parsing. SMS delivery status and pending messages are still processed when enabled. A server without ETags remains usable through normal fetch and deduplication.
4. Parse the Markdown table using its column names. Carry `↳` forward only within the same table. Strip formatting, decode entities, handle escaped pipes, bracketed labels, and simple parenthesized URLs. A missing table or malformed listing fails the run without advancing state.
5. Apply deterministic title filtering before deduplication and any future scoring.
6. Print only new matches plus summary counts, then atomically save the updated jobs and source ETag together. With SMS enabled, queue the new jobs in the same transaction and process the SMS outbox, including on HTTP 304 runs.

Dates are preserved as supplied (for example `Sep 12`), without inventing a year. `work_model` is preserved from its table column. `source_url` means the listing link in the job-title cell; the upstream raw README URL is stored separately in source metadata. Canonical URLs are populated only when a direct non-Jobright link is provided in the title or an optional Apply/Application column. The adapter does not follow Jobright pages or crawl employers to discover hidden URLs.

## Filtering

Edit `ACCEPTED_TITLE_KEYWORDS` and `REJECTED_TITLE_KEYWORDS` in `src/config.py`. These are literal phrases, not regular expressions. Matching ignores case and punctuation, normalizes Unicode and whitespace, and requires whole words. For example, `PRODUCT-MANAGER` matches `product manager`; `product managerial` does not.

A rejected phrase always wins; otherwise a title must contain an accepted phrase. Defaults favor product manager, analyst, operations, strategy, and management titles. Rejection terms include the requested bad matches plus common seniority markers (`sr`, `staff`, `vp`, `head of`, `leader`). This is intentionally a transparent heuristic: `Principal Accounts` could cause a false negative, and a generic Product Manager title could still require significant experience. No geographic, eligibility, graduation-year, salary, or description-level inference is performed.

Keyword changes automatically invalidate the ETag optimization so unchanged upstream content is re-evaluated. Rejected jobs are not marked seen, allowing them to become new matches after a policy change. If changing parser or normalization semantics, bump the parser version in `policy_fingerprint()` or run with `--force`.

## Identity and JSON persistence

`src/dedupe.py` isolates state storage. `data/seen_jobs.json` has this schema:

```json
{
  "version": 1,
  "source": {"url": "raw README URL", "etag": "HTTP validator", "policy": "filter fingerprint"},
  "jobs": {"sha256 job_id": {"company": "...", "title": "..."}}
}
```

Each stored job includes all fields from the `Job` dataclass. The SHA-256 identity hashes a JSON array containing normalized company, title, location, and canonical-or-source URL. Text identity ignores case and repeated whitespace. URL normalization removes fragments and known tracking parameters, sorts query parameters, and preserves significant query IDs and path case. Date and work model do not affect identity.

Relevant duplicate rows within a single fetch count as already seen too. History is retained when listings disappear; reappearing identical listings do not alert again. Different Jobright listing IDs remain different identities even if the visible text is identical. Location aliases are not merged.

Writes use a flushed temporary file and atomic replacement. Invalid JSON or unknown schema fails closed; restore a backup instead of silently discarding history. A local advisory lock serializes runs sharing a state path. Separate machines need shared storage or the workflow serialization below.

Output is flushed before saving. A crash or failed state commit can cause a repeated alert on retry; this favors repetition over silent loss. Console output is not a transactional delivery system. SMS has a persistent outbox, but remote sends and Git commits cannot be atomic; this does not guarantee exactly-once notifications.

## ATS detection

`src/ats.py` checks hostname boundaries for Greenhouse, Workday, Lever, Ashby, iCIMS, and SmartRecruiters. Subdomains are accepted; names appearing in query strings or unrelated domains are not. Custom employer domains and indirect Jobright links return `Unknown`. Extend `ATS_DOMAINS` to add verified domains. ATS detection never makes extra network calls.

## GitHub Actions

Place the **contents of this project directory at your repository root**, including `.github` and the tracked `data/seen_jobs.json`. The workflow must be on the default branch. Enable Actions and allow the workflow's `contents: write` permission. Branch rules must permit this bot to push; otherwise the persistence step will fail visibly and the next run may repeat matches.

`.github/workflows/poll_jobs.yml` supports manual `workflow_dispatch` and runs at minutes 7 and 37 of each hour (UTC). It installs dependencies, runs tests, runs the scraper with SMS enabled, and commits only changed state with `chore: update seen jobs`. There is no `push` trigger, so state commits cannot loop this workflow. It always checks out the default branch, including for manual runs, and serializes poll jobs with a shared concurrency group. GitHub schedules can be delayed and are not exact timers; see [GitHub's schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Runners are ephemeral: **persistence comes from the bot commit**, not the runner filesystem or a cache. The ETag and history are in the same tracked file, so both survive. If nothing changes, there is no commit. A final pull/rebase accommodates unrelated concurrent edits; conflicting state changes or blocked pushes fail instead of force-pushing. Avoid other writers to this state file during workflow runs. Commit-backed JSON is intended for modest personal usage and will grow over time.

New matches appear in the Actions Poll step logs and produce SMS digests through the configured Twilio account. The Persist state step runs even after a polling/SMS error so failed delivery records survive; the workflow still reports failure. The scraper workflow has been deployed and successfully run on GitHub.

## Limitations and extension points

- The repository controls freshness and retention. Listings added and removed between polls can be missed. A listing disappearing does not mark a job closed.
- The parser targets this source's Markdown schema, not arbitrary Markdown or HTML tables. Format changes fail visibly and leave the prior ETag available for retry.
- Jobright links usually conceal the employer ATS; canonical apply URLs remain null when unavailable.
- Title filtering cannot establish actual new-grad eligibility. Review matches before acting.
- JSON history is unbounded, and Git history grows with state commits. Back up state and migrate storage when volume warrants it.
- Windows needs a replacement lock implementation (or WSL).

The `Job` dataclass is the boundary for new adapters under `src/sources/`. Keep source fetching/parsing separate from `filters.py`, `ats.py`, and `dedupe.py`. Future LLM scoring belongs after deterministic filters and discovery. Resume tailoring, LaTeX generation, PDF compilation, and ATS workflows should be separate consumers with explicit delivery state. Twilio delivery is isolated in `src/notifications.py`. Replace the isolated JSON storage functions with Supabase/Postgres when needed. None of these future integrations is implemented in v1.

## Verification

Verified locally with Python 3.11: 35 standard-library unittest tests passed, including SMS queue persistence, no-backlog behavior, delivery receipts, bounded retries, uncertain sends, environment loading, and API error sanitization. Tests cover real-format parsing, company continuation, bracketed titles, malformed input, URL identity, atomic write failure, filtering, all six ATS platforms, HTTP retries, ETag handling, policy changes, and repeat runs.

Live run on 2026-09-13: 549 listings, 429 rejected, 120 new matches. The next conditional request returned unchanged. A forced repeat reported 120 already seen and no new matches. Counts are a snapshot of a changing upstream source.


## Twilio SMS

The scheduled workflow enables SMS. Set these four **repository Actions secrets** (already configured for the deployed repository):

- `ACCOUNT_SID`
- `AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER` (SMS-capable sender)
- `TO_PHONE_NUMBER` (your recipient, verified in trial accounts)

For local use, copy `.env.example` to `.env` and populate it. `.env` is Git-ignored. The loader supports literal `KEY=value` lines, optional matching quotes, and full-line comments; it performs no shell expansion or inline-comment processing. Existing process variables take precedence. Never commit credentials. Phone numbers use E.164 format (`+` and country code, no punctuation).

```sh
python -m src.main --sms
python -m src.main --test-sms
```

`--test-sms` implies SMS and queues a **one-time** `test-v1` connection message. Repeating it with the same state will not send a second test. In GitHub Actions, manually run Poll jobs and check `test_sms` for the same behavior. Normal runs send nothing when no jobs are newly discovered and no retry is pending. Running without `--sms` retains console-only behavior; jobs seen in console-only runs are not backfilled into SMS later.

Digests include the total new count, job names and links that fit within 900 characters, and a link to the private repository's Actions logs for the full list. One API message is attempted per run; longer texts can be billed as multiple SMS segments. The log URL in `digest_body()` targets this repository; change it if reusing the project elsewhere.

The `sms` object in `seen_jobs.json` stores digest bodies, covered job IDs, attempt counts, Twilio message SIDs, and status. It never stores your token or phone numbers. Existing job history is left alone, so enabling SMS does not alert the backlog.

- `pending`: waiting for a send attempt; at most one message is attempted each run.
- `accepted`: Twilio accepted the request, **not confirmation of handset delivery**. Subsequent polls fetch its delivery status, including when upstream is unchanged.
- `delivered`: Twilio reports delivery.
- `blocked`: permanent API rejection or three failed attempts. Fix the account/number problem before manually retrying.
- `uncertain`: a timed-out/interrupted POST might already have sent. Check Twilio Messaging logs before retrying to avoid duplicates.

HTTP 429 and confirmed failed/undelivered receipts retry on later runs, up to three attempts. Other 4xx errors are blocked. POST network/5xx errors are uncertain and are not blindly retried. Read-only delivery checks retry on subsequent scheduled runs. Accepted messages without a final receipt remain accepted rather than being resent.

After resolving a blocked failure, or confirming an uncertain message was not sent:

```sh
python -m src.main --retry-sms OUTBOX_ID
```

This requires the same up-to-date state as the scheduler; pull it first and avoid running local SMS concurrently with GitHub. It resets that item's attempt budget. If Twilio did send an uncertain message, reconcile the saved SID/status instead of resending.

The outbox is atomically saved before sending and after the result. GitHub commits state even on ordinary failure. A runner crash/cancellation or rejected Git push before persistence can still cause duplicate messages on the next run; no exactly-once guarantee is made. Twilio trial/registration restrictions can prevent delivery even when credentials are valid. Consult [Twilio message statuses](https://www.twilio.com/docs/messaging/api/message-resource) and the sanitized error code in workflow logs.
