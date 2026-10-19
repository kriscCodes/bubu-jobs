# bubu-jobs

A small Python 3.11+ job-alert pipeline. It pulls from three sources, in order:

1. **SimplifyJobs** `listings.json` (primary): https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json
2. **FindYourRoleFirst** public entry-level JSON (secondary, fail-soft): https://findyourrolefirst.click/api/public/entry-level
3. **Jobright** Product Management new-grad README (third): https://github.com/jobright-ai/2026-Product-Management-New-Grad/blob/master/README.md

It prints newly discovered relevant jobs and persists their identities in JSON. Optional Gmail email uses three environment settings; no database, LLM, or application automation is included.

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
2. Fetch each source with a network timeout (90 seconds for the ~13MB SimplifyJobs JSON, 30 seconds otherwise) and at most three attempts. Retry transient connection errors and HTTP 429/500/502/503/504 with bounded backoff; honor numeric Retry-After up to 60 seconds. Send `If-None-Match` and `If-Modified-Since` when saved validators exist. HTTP 304 skips downloading and parsing that source. FindYourRoleFirst is fail-soft: a request or schema error is logged and the run continues with the other sources. SimplifyJobs and Jobright still fail closed.
3. Parse SimplifyJobs rows where `active && is_visible`, `date_posted` is within the last 14 days, the title passes the PM filters (matched across every category; `category == "Product"` is not trusted), and at least one location is in the US. Parse FindYourRoleFirst `tracks.product.jobs[]` with the same title + US filters. Parse the Jobright Markdown table using its column names as before.
4. Apply deterministic title filtering again, then **dedupe across sources**. Identity is the normalized apply URL (lowercase host, drop `utm_*` / `ref`, strip a trailing `/apply`); if that does not match, fall back to normalized company + title. The first source in the order above wins.
5. Print only new matches plus summary counts, then atomically save the updated jobs and per-source ETags together. With email enabled, queue new jobs in the same transaction and process the email outbox, including on all-304 runs.

### First-run suppression (do not flood on deploy)

Adding a source must not mass-email the current backlog.

- Anything already stored in `data/seen_jobs.json` stays seen. Matching uses the same normalized apply URL **or** company + title keys, so a SimplifyJobs ATS link that is the same role as an older Jobright row is not re-emailed.
- **Brand-new sources only** (SimplifyJobs and FindYourRoleFirst, the first time each one successfully downloads): listings with `date_posted` older than about 3 days are written into `seen_jobs.json` and counted as `First-run seeded`, but they are **not** queued for email. Listings from the last ~3 days can still alert, unless they already match a seen job.
- Jobright is not a new source; it does not use the 3-day seed. After a source’s first successful download, `state.sources.<name>.seeded` is set and later runs alert normally.

Dates from JSON sources are rendered from their unix/ISO timestamps (for example `Oct 15`). Jobright dates are preserved as supplied. `source_url` is the listing/apply link from that source. Canonical URLs are the direct ATS link when the source already provides one; Jobright wrappers remain unresolved unless `--resolve-urls` is used.

## Filtering

Edit `ACCEPTED_TITLE_KEYWORDS` and `REJECTED_TITLE_KEYWORDS` in `src/config.py`. These are literal phrases, not regular expressions. Matching ignores case and punctuation, normalizes Unicode and whitespace, and requires whole words. For example, `PRODUCT-MANAGER` matches `product manager`; `product managerial` does not.

A rejected phrase always wins; otherwise a title must contain an accepted phrase. Defaults favor product manager, analyst, operations, strategy, and management titles. Rejection terms include the requested bad matches plus common seniority markers (`sr`, `staff`, `vp`, `head of`, `leader`). **Exception:** `Senior Associate` / `Sr Associate` is stripped before the `senior`/`sr` check so entry-level titles at Capital One, LSEG, and Amex still match, while `Senior Product Manager`, `Sr PM`, Lead, Principal, and Director do not.

SimplifyJobs and FindYourRoleFirst also require at least one US location. Jobright is not US-filtered (it remains the legacy third source). This is intentionally a transparent heuristic: `Principal Accounts` could cause a false negative, and a generic Product Manager title could still require significant experience. No eligibility, graduation-year, salary, or description-level inference is performed.

Keyword changes automatically invalidate the ETag optimization so unchanged upstream content is re-evaluated. Rejected jobs are not marked seen, allowing them to become new matches after a policy change. If changing parser or normalization semantics, bump the parser version in `policy_fingerprint()` or run with `--force`.

## Identity and JSON persistence

`src/dedupe.py` isolates state storage. `data/seen_jobs.json` has this schema:

```json
{
  "version": 1,
  "source": {"url": "raw README URL", "etag": "HTTP validator", "policy": "filter fingerprint"},
  "sources": {
    "simplify": {"url": "...", "etag": "...", "policy": "...", "seeded": true},
    "findyourrolefirst": {"url": "...", "etag": "...", "seeded": true},
    "jobright": {"url": "...", "etag": "...", "policy": "..."}
  },
  "jobs": {"sha256 job_id": {"company": "...", "title": "...", "source": "simplify"}}
}
```

`source` remains the Jobright cache for backward compatibility. `sources` holds per-source ETags, Last-Modified validators, and the first-run `seeded` flag. Each stored job includes all fields from the `Job` dataclass, including `source` and `date_posted_ts` when known. The SHA-256 identity hashes a JSON array containing normalized company, title, location, and canonical-or-source URL. **Alerting** additionally treats a job as already seen when its normalized apply URL **or** its normalized company + title matches any stored job. URL normalization for that match lowercases the host, drops `utm_*` / `ref`, and strips a trailing `/apply`. Date and work model do not affect identity.

Relevant duplicate rows within a single fetch count as already seen too. History is retained when listings disappear; reappearing identical listings do not alert again. Different Jobright listing IDs remain different identities even if the visible text is identical. Location aliases are not merged.

Writes use a flushed temporary file and atomic replacement. Invalid JSON or unknown schema fails closed; restore a backup instead of silently discarding history. A local advisory lock serializes runs sharing a state path. Separate machines need shared storage or the workflow serialization below.

Output is flushed before saving. A crash or failed state commit can cause a repeated alert on retry; this favors repetition over silent loss. Console output is not a transactional delivery system. Email has a persistent outbox, but remote sends and Git commits cannot be atomic; this does not guarantee exactly-once notifications.

## ATS detection

`src/ats.py` checks hostname boundaries for Greenhouse, Workday, Lever, Ashby, iCIMS, and SmartRecruiters. Subdomains are accepted; names appearing in query strings or unrelated domains are not. Custom employer domains and indirect Jobright links return `Unknown`. Extend `ATS_DOMAINS` to add verified domains. ATS detection never makes extra network calls.

## GitHub Actions

Place the **contents of this project directory at your repository root**, including `.github` and the tracked `data/seen_jobs.json`. The workflow must be on the default branch. Enable Actions and allow the workflow's `contents: write` permission. Branch rules must permit this bot to push; otherwise the persistence step will fail visibly and the next run may repeat matches.

`.github/workflows/poll_jobs.yml` supports manual `workflow_dispatch` and runs every 10 minutes, at minutes 7, 17, 27, 37, 47, and 57 of each hour (UTC). It installs dependencies, runs tests, runs the scraper with email enabled, and commits only changed state with `chore: update seen jobs`. There is no `push` trigger, so state commits cannot loop this workflow. It always checks out the default branch, including for manual runs, and serializes poll jobs with a shared concurrency group. GitHub schedules can be delayed and are not exact timers; see [GitHub's schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Runners are ephemeral: **persistence comes from the bot commit**, not the runner filesystem or a cache. The ETag and history are in the same tracked file, so both survive. If nothing changes, there is no commit. A final pull/rebase accommodates unrelated concurrent edits; conflicting state changes or blocked pushes fail instead of force-pushing. Avoid other writers to this state file during workflow runs. Commit-backed JSON is intended for modest personal usage and will grow over time.

New matches appear in the Actions Poll step logs and produce email digests through the configured Gmail account. If EMAIL_PASSWORD is missing, jobs are queued without sending. The Persist state step runs even after a polling/email error so failed delivery records survive; the workflow still reports failure on actual delivery errors. The scraper workflow has been deployed and successfully run on GitHub.

## Limitations and extension points

- The repository controls freshness and retention. Listings added and removed between polls can be missed. A listing disappearing does not mark a job closed.
- SimplifyJobs and Jobright parsers fail visibly on schema changes and leave the prior ETag available for retry. FindYourRoleFirst logs a warning and is skipped.
- Jobright links usually conceal the employer ATS; canonical apply URLs remain null when unavailable. The newer JSON sources usually already provide direct ATS URLs.
- Title filtering cannot establish actual new-grad eligibility. Review matches before acting.
- JSON history is unbounded, and Git history grows with state commits. Back up state and migrate storage when volume warrants it.
- Windows needs a replacement lock implementation (or WSL).

The `Job` dataclass is the boundary for new adapters under `src/sources/`. Keep source fetching/parsing separate from `filters.py`, `ats.py`, and `dedupe.py`. Future LLM scoring belongs after deterministic filters and discovery. Resume tailoring, LaTeX generation, PDF compilation, and ATS workflows should be separate consumers with explicit delivery state. Gmail delivery is isolated in `src/email_notifications.py`. The prior Twilio adapter remains available for explicit local use but is no longer called by the schedule. Replace the isolated JSON storage functions with Supabase/Postgres when needed. None of these future integrations is implemented in v1.

## Verification

Verified locally with Python 3.11: 50 standard-library unittest tests passed, including email MIME formatting, SMTP TLS/authentication, queue persistence, failed-SMS migration, no-backlog behavior, bounded retries, uncertain sends, environment loading, and API error sanitization. Tests cover real-format parsing, company continuation, bracketed titles, malformed input, URL identity, atomic write failure, filtering, all six ATS platforms, HTTP retries, ETag handling, policy changes, and repeat runs.

Live run on 2026-09-13: 549 listings, 429 rejected, 120 new matches. The next conditional request returned unchanged. A forced repeat reported 120 already seen and no new matches. Counts are a snapshot of a changing upstream source.


## Gmail email alerts

Email replaces SMS in the scheduled workflow. No Twilio credentials or registration are needed. The old SMS state remains as history and is never sent by the schedule. Pending/blocked job alerts from that queue are migrated into email once; the original seen-job backlog and the SMS connection test are excluded.

Set these **repository Actions secrets**:

| Secret | Purpose |
| --- | --- |
| `EMAIL_SENDER` | Gmail account used to send and sign in |
| `EMAIL_RECIPIENT` | One destination email address; may equal the sender |
| `EMAIL_PASSWORD` | Google App Password for the sender, not its normal account password |

Sender and recipient are currently configured to the owner's Gmail account for testing. This chat's Gmail connector can send a manual test, but its authorization is not available to GitHub Actions. Create the sender's [Google App Password](https://myaccount.google.com/apppasswords) and save it as `EMAIL_PASSWORD`. Google requires [2-Step Verification for App Passwords](https://support.google.com/accounts/answer/185833); some account policies may prevent using them.

For local use, add the same three variables to `.env` (see `.env.example`). `.env` is ignored by Git. The loader accepts literal `KEY=value`, optional matching quotes, and full-line comments; it performs no shell expansion. Existing process environment values win. Existing Twilio variables can remain in `.env` but are unused by email.

```sh
python -m src.main --queue-email  # Fetch and save pending email; no credentials needed
python -m src.main --email        # Fetch and send at most one queued digest
python -m src.main --test-email   # One-time SMTP connection test; implies email
```

In Actions, run Poll jobs with `test_email` checked for the SMTP test. The saved `email.test-v1` record prevents repeated connection-test emails. A manual test sent through the chat Gmail connector is separate from this automated SMTP test.

The workflow keeps collecting pending email if `EMAIL_PASSWORD` is missing, with a visible warning. A requested test fails visibly if the password is missing. Once configured, scheduled runs automatically send pending digests. With valid settings and nothing new or pending, no email is sent. Runs without any notification flag stay console-only and do not queue email.

### Email contents and delivery

Each digest includes every matching job's company, title, location, work model, posted date, ATS, and application/listing URL. Both plain-text and escaped HTML versions are sent. Links are directly in the message; recipients do not need access to this private repository. HTML is generated from escaped source data. There is one recipient and at most one email submission per invocation.

`email` in `data/seen_jobs.json` stores covered job IDs, rendered bodies, attempt count, and status. It stores no password and no recipient list. A submitted message's deterministic Message-ID includes the sender domain. Recipients and credentials are resolved at send time: changing settings also changes where still-pending emails go.

- `pending`: waiting for a send or a later retry.
- `sending`: saved immediately before SMTP; a process interrupted here becomes uncertain.
- `submitted`: SMTP accepted it. This is not proof of inbox placement or reading. Bounces and spam placement are not monitored.
- `blocked`: authentication/permanent rejection or three failed attempts.
- `uncertain`: connection dropped during sending; check Sent mail before resending.

SMTP uses `smtp.gmail.com:465` with verified TLS and a 30-second timeout. Temporary SMTP 4xx rejections and failures before sending retry on later runs, at most three attempts. Ambiguous send failures are held, not automatically repeated. A blocked/uncertain record stops further submissions until resolved. Diagnose without exposing passwords or server responses containing addresses.

After fixing a blocked issue, or confirming an uncertain message was not sent:

```sh
python -m src.main --retry-email OUTBOX_ID
```

Pull current state first and avoid concurrent local/GitHub sending. The command resets the attempt budget for that entry. If the email was already sent, reconcile its state instead of retrying. Message-ID reuse can help diagnosis but is not a guaranteed server deduplication mechanism.

Atomic local saves and bot commits preserve the queue during ordinary failures. A runner crash, cancellation, or failed Git push after SMTP acceptance can still cause repeats; remote SMTP and Git are not a single transaction. History grows over time.

### Switching to a dedicated sender later

Create the dedicated Gmail account, enable 2-Step Verification, and generate its own App Password. Replace `EMAIL_SENDER` and `EMAIL_PASSWORD` in repository secrets. Change `EMAIL_RECIPIENT` when ready to send to another person. No code changes are required. The current configuration only sends to the owner.
