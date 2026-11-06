# Jobpipe · Your next move

**A personal job-search workspace that turns scattered postings into a manageable shortlist.**

Job hunting involves more than finding links: you need to decide which roles are
worth pursuing, adapt your application, and remember what happens next. Jobpipe
brings those steps together in a local dashboard, using your CV and your own
preferences to guide the search.

Jobpipe is an open-source MVP for individual job seekers. Its goal is to reduce
repeated review and application preparation, while keeping you in charge of the
decision. It does not submit applications or guarantee interviews.

[Getting started](#getting-started) · [Features](#features) ·
[How decisions work](#how-decisions-work) · [Gmail setup](#connect-gmail-without-terminal-commands) ·
[Technical overview](#technical-overview) · [License](#license)

## Who it is for

Jobpipe is useful when you collect opportunities from several places and want one
workspace to assess them against your experience. You bring your CV, search
criteria, and job sources; Jobpipe helps organize and prepare the opportunities.

It is a personal assistant, rather than a recruitment marketplace or a shared
applicant-tracking system. There is no hosted service, recruiter network, paid
Jobpipe subscription, or multi-user account system included. AI providers and
other services may have their own costs and account requirements.

The useful measure of success is more worthwhile applications and interviews,
not a larger number of collected jobs or a higher AI score.

## Features

| Area | What you can do |
| --- | --- |
| Discovery | Collect company-board jobs, import supported Gmail job alerts, or paste a posting manually |
| Preferences | Set roles, skills, exclusions, locations, salary floor, sponsorship requirements, and AI limits |
| Review | Browse scored opportunities, inspect gaps and evidence, and use a focused review queue |
| CV workspace | Upload Markdown or self-contained LaTeX, edit and save it, optionally score it or request improvements |
| Applications | Review tailored summaries, suggested CV bullets, cover letters, and LinkedIn notes |
| PDF export | Generate a tailored CV PDF for a job when you click the button |
| Tracking | Mark jobs applied, view seven-day follow-ups, and export a CSV |
| Feedback | Mark Interested or Not for me, with an optional dismissal reason |
| Custom agents | Create, test, and assign AI specialists to scoring, evidence, drafting, and CV stages |
| Efficiency | Filter and rank locally, merge exact duplicates, cap AI work, and save deferred candidates |

## How decisions work

A search follows this sequence:

1. **Collect:** gather postings from enabled sources and saved candidates.
2. **Identify duplicates:** compare source IDs, normalized URLs, and sufficiently
   detailed identical content before spending AI tokens.
3. **Screen locally:** apply the preferences you saved. Job-title phrases restrict
   titles when provided; excluded terms and location rules can remove listings.
4. **Rank locally:** prioritize preferred skills in titles and requirements over
   passing mentions in the description. Location matches, relocation signals,
   and posting dates break ties.
5. **Analyze within your limit:** send the highest-ranked eligible candidates
   to the chosen AI provider for fit scoring and evidence extraction.
6. **Prepare and review:** qualifying jobs receive application drafts. You decide
   whether to pursue them, generate a PDF, and apply yourself.

The repository starts with empty personal search terms. Set your preferences
before searching; generic defaults cannot know what a good job means for you.

### Fit, requirements, and uncertainty

A fit score is an AI assessment of the posting against your CV, not a probability
of getting hired. Eligibility is shown separately.

Required terms found in a posting are text signals. Missing terms remain unknown.
The sponsorship check detects explicit refusal language; it does not confirm
sponsorship simply because a posting mentions visas. You choose whether unknown
requirement information stays available for checking or is excluded.

Some preferences remain direct filters. For example, title phrases and location
rules can exclude a role before AI analysis. The salary check uses a stated annual
gross EUR maximum; it does not convert currencies or infer an unstated salary.

Job details can show exact posting and CV quotes returned by the evidence step.
Jobpipe checks that those quotes occur in the supplied text. This verifies their
origin, not whether the AI interpreted them correctly. Review important claims.

### Duplicate prevention and token efficiency

Different sources can point to one internal job. Jobpipe merges matching source
identities and canonical URLs, and exact normalized company/title/location/
description copies when the description has at least 200 characters. Missing
locations and short descriptions cannot trigger content merges.

Source references are retained. The longest available description is selected
before scoring. Already processed identities are skipped, while unprocessed
candidates persist for a later search and are checked against current preferences.

Existing exact-URL duplicates are hidden from the job list without deleting
history or drafts; applied records take precedence. Older records lack full
descriptions, so historical cross-site content matching is limited.

Similar-but-edited postings may remain separate. Automatic rescoring is not performed. Use explicit rescoring after saving a new CV; otherwise analyses and drafts continue to reflect their original inputs.

### Review and feedback

Enable **Focused review queue** to page through results using the size set in
Preferences. It shows available results in score order and does not manufacture
matches to fill a quota.

**Not for me** hides a job from lists; **Clear feedback** reverses that decision.
Feedback is stored separately from application status. It does not yet train a
model, adjust ranking, or silently change your preferences.

## Rescore jobs after changing your CV

Save your updated CV in **My CV** first. Unsaved editor changes are not included.

- Open a job and choose **Rescore with saved CV** for a single eligible job.
- Above Opportunities, choose **Rescore jobs with an older CV** for a batch.

The preview lists the jobs and count before you confirm AI usage. Batch selection
takes highest-scored jobs whose CV fingerprint is older or unknown, up to your
**Jobs per search** limit. Applied, dismissed, and hidden duplicate records are
excluded. Run another batch to continue through older results.

Rescoring uses saved posting descriptions, the current saved CV, and current
AI/agent settings; it does not fetch a fresh posting or rerun source discovery.
It reevaluates fit, evidence, salary/language checks, and drafts when shortlisted.
Local collection/ranking filters are not reapplied in this explicit review action.
A CV change after preview invalidates confirmation.

Successful rescoring replaces the visible analysis and draft. Previous score,
status, analysis, and draft are archived in SQLite for preservation; there is no
history browser or restore button yet. Failed AI requests keep the previous
result. If a job no longer qualifies, the old active draft is removed after archiving.
Original discovery dates, feedback, and source links are retained.

Job details show whether the score used the current CV or an older/unknown one.
Older records without saved descriptions cannot be reassessed; import their full
description again. Applied jobs are never reassessed through this action. Progress
and stopping use the existing Activity controls.

## Custom agents

To set up your first specialist:

1. Open **Agents** and click **New agent**.
2. Give it a name and describe the emphasis or writing style you want.
3. Keep **Use Preferences provider**, or choose Codex or Anthropic. Optionally set a model.
4. Select the agent for the desired stage under **Pipeline assignments**.
5. Choose that stage in **Test before assigning**, paste representative sample input,
   and click **Run preview**. For scoring, include both CV and posting text; for
   CV stages, provide a Markdown CV.
6. Review the preview, adjust the instructions if needed, then click
   **Save agents and assignments**.

For example, a drafting specialist might say:
“Write concise, direct applications. Emphasize relevant technical work supported
by my CV. Avoid generic praise and do not exaggerate my responsibilities.”

One agent can serve several stages, or you can assign a different specialist to
each. Choose **Jobpipe default** to stop using a custom specialist for a stage.
Preview calls use provider allowance just like other AI calls.


Open **Agents** to create a saved AI specialist with a name, instructions, provider,
and optional model. Duplicate an existing agent to try another approach.
Under **Pipeline assignments**, select a specialist or the Jobpipe default for:

- Job scoring
- Evidence review
- Application drafting
- CV scoring
- CV editing (suggestions and prompted revisions)
- Natural wording

Save the library and assignments to activate them. An agent replaces the existing
call at its stage; assigning one does not add a new pipeline step. Custom provider
choices still require that provider's credentials. A blank model uses the selected
provider's configured default. Agents cannot configure commands or API endpoints.

Use **Test before assigning** with sample input to preview the assignments shown,
including unsaved edits. This makes an AI call without saving a job or CV.
Scoring and CV previews use their normal response validators; evidence and drafting
previews are illustrative, while production retains its existing contracts.

Export/import JSON to move agent definitions between installations. Import replaces
the unsaved library for review; save to activate. Exports include instructions, so
check for personal information before sharing. Never put credentials in instructions.

Saving changes to an agent increments its version. New job analyses, drafts, and
CV review responses identify the agent/version used; old outputs remain unchanged.
Deleting an agent in the UI clears its assignments back to defaults.

These are saved instruction/model profiles, not external framework executables.
Jobpipe retains factuality instructions, score validation, exact-quote checks, and
manual application/CV saving. Model compliance still requires user review. Source
collection, deduplication, and database updates remain ordinary code.

## Supported sources

| Source | Connection |
| --- | --- |
| Arbeitnow | Built-in collection, enabled in Preferences |
| Greenhouse company boards | Add a public company board URL in Job sources |
| Lever company boards | Add a public company board URL, including EU boards |
| LinkedIn, Glassdoor, Indeed, StepStone | Supported job-alert emails through Gmail |
| XING, WeAreDevelopers, and other sites | Paste the full description and original link in Add a posting |

Supported board URL formats include:

- `https://job-boards.greenhouse.io/company-slug`
- `https://boards.greenhouse.io/company-slug`
- `https://jobs.lever.co/company-slug`
- `https://jobs.eu.lever.co/company-slug`

Use **Preview listings**, then **Save source**. A general job-search website URL
is not an automatic connector. For manual entries, provide the description as
well as the link so the AI has text to evaluate.

## Getting started

### Choose your environment

| Environment | Setup path |
| --- | --- |
| macOS | Docker Desktop, or native Python and Node.js |
| Windows | Docker Desktop with Linux containers; WSL 2 is the recommended development alternative |
| Linux desktop | Docker Engine with the Compose plugin, or native Python and Node.js |
| Remote Linux machine | Docker with an SSH tunnel; keep the dashboard private |

The search lock currently uses a Unix facility. Run on Windows through Docker
or WSL 2, rather than native Windows Python.

### Docker setup

Install [Docker Desktop](https://docs.docker.com/desktop/) on macOS or Windows.
For Linux, install [Docker Engine](https://docs.docker.com/engine/install/) and the
[Compose plugin](https://docs.docker.com/compose/install/linux/).
For Windows-specific requirements, see [Docker's Windows guide](https://docs.docker.com/desktop/setup/install/windows-install/).

Download the repository, or clone it if you have access:

```sh
git clone https://github.com/aleereza96/jobpipe.git
cd jobpipe
docker compose up --build -d
```

Start Docker Desktop before running Compose. The initial build needs internet
access to download Node, Python dependencies, and the Codex CLI.

Open [localhost:8787](http://localhost:8787).

### Connect an AI provider

**Codex is the default.** Sign in without terminal commands:

1. Open **Preferences → Connect Codex** and click **Connect / Retry**.
2. Wait for the temporary device code, then click **Open OpenAI sign-in**.
3. Approve sign-in on OpenAI's website and enter the code. Keep Jobpipe open.
4. Jobpipe checks completion automatically and shows **Connected**.

Use **Cancel** to stop a pending flow, **Connect / Retry** after failure or expiry,
and **Disconnect** to remove the saved Codex login. A pending attempt is limited
to ten minutes; restarting Jobpipe discards its in-memory progress. Device login
may need enabling in your ChatGPT security or workspace settings. See the
[official authentication guide](https://learn.chatgpt.com/docs/auth).

Jobpipe never requests your OpenAI password. Codes are temporary and must not be
shared. Login output is filtered rather than returned as raw logs, and saved
credentials stay in the existing Docker volume. Docker still needs access to
OpenAI's authentication and inference services: UI sign-in cannot fix blocked
network routes, proxy issues, or TLS errors.

For troubleshooting, the equivalent terminal command remains:
`docker compose exec jobpipe codex login --device-auth`.
Use **Check connection** to check the saved CLI login; it does not run an
inference request or prove end-to-end AI connectivity.

**Anthropic is optional.** Copy `.env.example` to `.env`, set
`ANTHROPIC_API_KEY`, then recreate the container:

```sh
docker compose up -d --force-recreate
```

Choose Anthropic and a model available to your account in Preferences. The SDK
is included in the Docker image. Keys are not entered into the dashboard.

AI access is separate from Jobpipe's MIT license. Provider availability, usage
limits, and charges depend on your account.

### Your first search

1. Open **My CV**, upload a UTF-8 `.md` or `.tex` file, review it, and save.
2. Set your roles, skills, locations, requirements, and exclusions in **Preferences**.
3. Set **Jobs per search** to a small trial budget, such as 10.
4. Add company boards or connect Gmail if desired.
5. Choose **Find opportunities** and review Activity.
6. Inspect promising jobs, verify their requirements, and review the drafts.
7. Generate a PDF if useful, apply on the original website, and mark the job applied.

The job limit is not a token or AI-call limit. A successful analyzed job normally
uses scoring and evidence calls; a qualifying job also uses a drafting call.
Optional CV reviews make additional calls. Evidence failure does not discard an
otherwise scored job. Stop controls preserve completed results.

### Native setup on macOS, Linux, or WSL 2

Install Python 3.10+ and a supported Node.js/npm environment. Then, from the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm install -g @openai/codex
codex login
python server.py
```

Open [localhost:8787](http://localhost:8787). For native Anthropic usage, also
install `anthropic` and export `ANTHROPIC_API_KEY` in the shell before starting.
Native execution does not automatically load a `.env` file; Compose uses that file.

The server creates missing CV/config files from templates. Set `JOBPIPE_DATA_DIR`
to an existing writable directory if you want data outside the source folder.

### Remote Linux setup

Start the Docker deployment on the remote host using the same Compose file.
From your own computer, forward its local dashboard port:

```sh
ssh -L 8787:127.0.0.1:8787 your-user@your-server
```

Keep the SSH session open and browse to `http://localhost:8787`. The dashboard has
no multi-user authentication and is intended for local access. Do not publish its
port to the internet. Remote OAuth setup can require additional configuration;
local desktop deployment is the simplest path for Gmail.

## Connect Gmail without terminal commands

Once Jobpipe is running, Gmail setup and imports happen through the browser:

1. Open **Job alerts → Set up Google connection · no terminal needed**.
2. Follow the link to Google Cloud Console. Create/select a project, enable the
   Gmail API, and configure Google Auth Platform branding and audience.
3. If the Google app is in Testing, add the Gmail accounts as test users.
4. Create an OAuth client of type **Desktop app**, then download its JSON.
5. Upload it using **Google Desktop app JSON**. No renaming or manual file move is needed.
6. Click **Connect Gmail**, sign in on Google's page, and approve read-only access.
   Repeat for additional accounts.
7. Choose **Import alerts**, or start a search.

If the app configuration is already saved, start at **Connect Gmail**.
Google's one-time setup still happens on Google's website; see its
[Gmail API setup guide](https://developers.google.com/workspace/gmail/api/quickstart/python).
Testing grants may expire after seven days and require reconnection.

The importer checks the last 14 days of supported alerts. A single listing with a
sufficiently detailed, explicitly labeled description can enter the search.
For link-only alerts, open the posting and paste its description into the alert row.

To replace the Google client configuration, disconnect existing accounts first.
Disconnect removes the local grant but keeps imported leads. Revoke access through
your Google Account if you also want to remove the grant at Google.

## CVs and application drafts

Markdown and common self-contained LaTeX CVs are supported. LaTeX is converted
to text without compiling it; custom macros and templates may extract imperfectly.
Check the editor before saving.

**Score CV** and **Suggest improvements** are optional. Apply individual suggestions,
review the resulting text, then save to use it for future searches. Application
drafts are instructed to use CV facts, but you should still verify every claim.

### Prompted edits and natural wording

In **My CV**, enter an editing request under **Ask AI to update your CV**, then
choose **Propose requested changes**. Include the real details you want added,
the experience to change, and the role or tone you want to emphasize. For example:
“Emphasize backend work in my latest role. Add this fact: I built the internal
reporting API using Python.”

Jobpipe proposes up to five anchored prose edits. Review each before/after pair,
choose **Apply edit**, and **Save CV** when satisfied. Requests use the current
editor contents and your configured AI provider. They do not save automatically
or update old job analyses and drafts. If you change the CV during generation,
the stale response is discarded.

**Make wording more natural** removes stiff phrasing and generic buzzwords while
preserving facts. This is a writing aid, not a promise to bypass AI detection.
New facts must come from your CV or your explicit editing request; verify the
result because model instructions cannot guarantee factual accuracy.

LaTeX uses the same conservative plain-prose editing rules as other CV suggestions.
Commands and special characters cannot be edited through this tool. New details
must fit an existing prose anchor; creating entire sections or restructuring a
template may require manual editing. Empty suggestions mean no safe edit passed
validation, rather than a successful rewrite.

PDFs are generated only when requested for a job with a saved draft. They use
Jobpipe's standard layout rather than compiling the uploaded LaTeX template.

## Data, privacy, and everyday operation

Jobpipe runs locally, but AI analysis is not offline: CV text, job descriptions,
and relevant candidate context are sent to your selected provider. Gmail read-only
permission can read mailbox contents; the importer limits its searches to
supported job-alert senders.

| Local item | Purpose |
| --- | --- |
| `config.json` | Your saved preferences |
| `cv-source.json` / legacy `cv.md` | Your saved CV |
| `jobs.db` | Jobs, feedback, source identities, and deferred candidates |
| `inbox/` | Manually added postings |
| `output/` | Drafts and exports |
| `gmail-client.json`, `.gmail/` | Google app configuration, account grants, and imported alerts |
| Docker `codex_home` volume | Saved Codex sign-in |

These personal files are excluded from Git and the image build context. OAuth
files remain local; they are not encrypted by Jobpipe. Protect your computer and
backups accordingly.

Docker mounts the project folder as `/data`. To back up, stop Jobpipe and copy
the folder including hidden data files. Treat the Codex volume separately; signing
in again is an alternative to backing it up.

```sh
docker compose stop
docker compose start
docker compose logs -f jobpipe
docker compose down
```

These commands preserve the data folder. Avoid `docker compose down -v` unless
you intend to delete the saved Codex login volume.

For updates, back up first, pull the source changes, and rebuild:

```sh
git pull --ff-only
docker compose up --build -d
```

Keep personal files when replacing application files. Existing data is not a
disposable example database.

### Configuration and troubleshooting

Copy `.env.example` to `.env` for Docker overrides. `JOBPIPE_PORT` changes the
host port; `TZ` changes the container time zone (default UTC). Set `CODEX_VERSION`
to pin the CLI package version for builds.

| Problem | What to check |
| --- | --- |
| Docker cannot connect | Start Docker Desktop or the Docker service |
| Port 8787 is occupied | Set another `JOBPIPE_PORT` in `.env` and recreate the container |
| No useful results | Review sources, title/skill terms, location filters, and relevance cutoff |
| AI search fails | Check provider login, model access, limits, timeout, and Activity |
| Gmail connection fails | Check Desktop client type, enabled Gmail API, test users, and grant expiry |
| A job looks duplicated | Edited descriptions or different URLs may evade conservative matching |
| CV edits do not change old scores | Save the CV, then use explicit single-job or batch rescoring |
| Python fails during locale startup | Use a valid UTF-8 locale; Docker already sets `C.UTF-8` |

## Technical overview

Jobpipe uses a Python HTTP server, a plain HTML/CSS/JavaScript dashboard, and
SQLite for persistent state. Docker packages the runtime and provider tooling.
There is no separate database service or frontend build step.

| Component | Responsibility |
| --- | --- |
| `server.py`, `web/` | Dashboard, API routes, and search controls |
| `jobpipe.py` | Collection, screening, scoring, drafting, and tracking |
| `sources.py`, `gmail_alerts.py` | Company-board and email-alert imports |
| `search_rank.py`, `dedup.py` | Local relevance, requirement checks, and identity matching |
| `ai_provider.py` | Codex and Anthropic adapters and score validation |
| `cv_source.py`, `cv_review.py`, `cv_pdf.py` | CV import, optional review, and PDF generation |

The API checks local Host/Origin values for dashboard requests. AI input is treated
as data; output is validated before use. An exclusive file lock prevents parallel
searches against one data folder. These measures support a local personal app;
they do not make it a public multi-user service.

For contributors, run the existing checks in an environment with dependencies installed:

```sh
python -m unittest discover -s tests -v
node --check web/app.js
docker compose config --quiet
```

The tests cover provider adapters, dashboard behavior, Gmail setup, CV workflows,
deduplication, and a simulated search. They do not verify live provider quality,
every external email format, or all platform combinations.

Command-line tools remain available through `python jobpipe.py --help`. The
optional legacy IMAP alert collector uses `GMAIL_ADDRESS` and
`GMAIL_APP_PASSWORD`; it is separate from the dashboard's Gmail OAuth importer.

## MVP status and feedback

This release is ready for hands-on trials of the current workflow. The next
improvements should come from actual search sessions: missed suitable jobs,
irrelevant recommendations, duplicate examples, confusing setup steps, and
application outcomes.

Known gaps include near-duplicate review, expired-posting verification, automatic
reassessment, richer eligibility interpretation, and learning from feedback.
No interview or hiring outcome has been validated by the automated tests.

When reporting an issue, include the step you took, what you expected, and what
happened. Remove CV details, emails, API keys, and account grants before sharing
screenshots or logs.

## License

Jobpipe is licensed under the [MIT License](LICENSE). You may use, modify, and
redistribute the software, including commercially, subject to its terms.
Dependencies and external services retain their own licenses and terms.
