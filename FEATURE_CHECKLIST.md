# Feature Checklist 💛

A little roadmap for Bubu Jobs. Crossed-out items are finished; open boxes are ideas we still want to build. The order below is a suggested path, not a fixed schedule.

## Done

- [x] ~~Pull jobs from Jobright’s Product Management new-grad GitHub list.~~
- [x] ~~Read the job table and carry the company name forward on “↳” rows.~~
- [x] ~~Save each job’s company, title, location, work model, date, and listing link.~~
- [x] ~~Recognize common ATS platforms when a direct application URL is available.~~
- [x] ~~Filter for relevant product roles and exclude obvious senior or unrelated jobs.~~
- [x] ~~Remember seen jobs so the same listings don’t keep coming back.~~
- [x] ~~Check every 10 minutes with GitHub Actions, with a manual run option too.~~
- [x] ~~Skip downloading and parsing the README when it hasn’t changed.~~
- [x] ~~Keep job history and notification queues between scheduled runs.~~
- [x] ~~Send email digests with job details and application links.~~
- [x] ~~Save pending emails and retry temporary failures without blindly repeating uncertain sends.~~
- [x] ~~Test email alerts from Kris’s Gmail account to himself.~~
- [x] ~~Add automated tests for parsing, filtering, deduplication, and notifications.~~
- [x] ~~Write a friendly README and a separate technical setup guide.~~

## Next: make alerts more useful

- [ ] Create a dedicated sender email account and switch the sender credentials.
- [ ] Set Bubu’s email as the recipient and test an alert with her.
- [ ] Tune the title filters after reviewing the matches we receive.
- [ ] Add preferences for location, remote/hybrid work, and graduation year.
- [ ] Pull in more jobs from different sites and company career pages.
- [ ] Normalize jobs from every source into the same format.
- [ ] Recognize the same job across different sources, even when the links differ.
- [ ] Find direct company application links where available.
- [ ] Retrieve full job descriptions for better matching and resume tailoring.
- [ ] Flag closed or expired listings when the source provides that information.

## Next: AI matching and a LaTeX resume editor

- [ ] Add a profile with Bubu’s experience, skills, interests, and job preferences.
- [ ] Score jobs with AI after the existing deterministic filters.
- [ ] Explain briefly why each job looks like a good fit and what requirements may be missing.
- [ ] Create a LaTeX resume editor with an editable base resume.
- [ ] Keep a confirmed record of experience and achievements for the AI to work from.
- [ ] Let AI tailor a copy of the resume to a selected job description.
- [ ] Let AI automatically iterate on the LaTeX draft, improving wording, relevance, and layout without inventing experience.
- [ ] Compile the LaTeX into a PDF and show a preview alongside the editor.
- [ ] Feed compilation errors and layout issues back into the AI for a bounded number of fixes.
- [ ] Show the changes between the original resume and each tailored version.
- [ ] Let Bubu review, edit, and approve the final version before using it.
- [ ] Save resume versions by job and download the final LaTeX and PDF files.

## Later: keep everything organized

- [ ] Add a simple page to browse, save, and dismiss job matches.
- [ ] Track applications, interviews, follow-ups, and outcomes.
- [ ] Let Bubu mark matches as useful or irrelevant to improve future filtering.
- [ ] Add digest frequency and notification preferences.
- [ ] Add a clear alert when a source stops working or changes its format.
- [ ] Move JSON storage to a shared database if the project outgrows it.

## Parked

- **Twilio SMS:** implemented and tested, but delivery required sender registration. Email replaced it; SMS is not active in the scheduled workflow.
- **Automatic job applications:** not planned for now. Bubu will use **“Manually Apply”** on Jobright and submit through the company’s career site.
