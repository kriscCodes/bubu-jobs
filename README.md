# Bubu Jobs <3

Hi Bubu, I hope you're doing okay. I built this out with codex to help you out. There's more stuff I wanna add but this is a good first draft. Turn gmail notifications on your phone for this. I'd also turn on zero2sudos ig story notifications since he has stuff sometimes as well. I have no idea how often this repo polls jobs and some of them aren't directly related they just happen to have product in them so just keep a look out for that until I implement the LLM features.

It checks three lists every 10 minutes:

1. **[SimplifyJobs New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions)** (primary) — fresh JSON listings from the last 14 days, US-only, with the same PM title filters as before
2. **[FindYourRoleFirst](https://findyourrolefirst.click/)** entry-level product jobs (secondary; skipped with a warning if it errors)
3. **[Jobright’s Product Management new-grad list](https://github.com/jobright-ai/2026-Product-Management-New-Grad)** (third, after the others)

It looks for roles like Associate Product Manager, Product Analyst, and Product Operations. “Senior Associate” titles (Capital One, LSEG, Amex) are kept; “Senior Product Manager”, “Sr PM”, Lead, Principal, and Director are still filtered out. Duplicate postings across sources are merged by apply URL, or by company + title when the URLs differ.

You’ll get an email when there are new matches, with the company, title, location, posted date, source, and a link to each listing. It remembers jobs it has already found, so you won’t keep getting the same list. If there’s nothing new, there’s no email.

The first run after adding a new source does **not** email the whole backlog: anything already in `seen_jobs.json` stays seen, and listings older than about 3 days from a brand-new source are recorded quietly so the first deploy is not a flood.

## Setup

1. Create a [Jobright account](https://jobright.ai/) and sign in. I recommend you do this with both your mobile and your laptop.
2. Open the job link in your email.
3. Click **“Manually Apply”** on Jobright to go to the company’s career site.
4. Review the requirements and submit your application there.

Tip:
Keep a resume handy on your mobile files in case you see an opening and its easy to apply to. Better to be fast than have to wait hours. Hopefully by next week I have the llm feature available though.

---

If you want to add stuff go ahead and do so or just let me know here or open a PR or something. The [technical guide](docs/SETUP.md) has everything you need.

See the [feature checklist](FEATURE_CHECKLIST.md).
