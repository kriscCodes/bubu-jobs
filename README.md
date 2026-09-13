# Bubu Jobs <3

Hi Bubu, I hope you're doing okay. I built this out with codex to help you out. There's more stuff I wanna add but this is a good first draft. Turn gmail notifications on your phone for this. I'd also turn on zero2sudos ig story notifications since he has stuff sometimes as well. I have no idea how often this repo polls jobs and some of them aren't directly related they just happen to have product in them so just keep a look out for that until I implement the LLM features.

It checks [Jobright’s Product Management new-grad job list](https://github.com/jobright-ai/2026-Product-Management-New-Grad) every 10 minutes. That’s the only place it pulls jobs from right now. It looks for roles like Associate Product Manager, Product Analyst, and Product Operations, and filters out obvious senior roles and unrelated jobs.

You’ll get an email when there are new matches, with the job details and a link to each listing. It remembers jobs it has already found, so you won’t keep getting the same list. If there’s nothing new, there’s no email.

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
