# Jobpipe · Your next move

A local dashboard for your job search: collect postings, match them to your CV,
review application drafts, and track applications and follow-ups. Nothing is
submitted automatically.

## Start with Docker

Start Docker Desktop first. In this folder, run:

```sh
docker compose up --build -d
```

Open **http://localhost:8787**. The first build downloads Node, Python dependencies,
and the official Codex CLI. It needs access to Docker Hub, Debian, PyPI and npm.

Connect your ChatGPT account from a terminal in this folder:

```sh
docker compose exec jobpipe codex login --device-auth
```

Open the URL shown in the terminal, sign in, and enter its one-time code. Device
code login may need enabling in your ChatGPT security settings or by your workspace
admin. Then open **Preferences → Check connection** in the dashboard.

Your sign-in is stored separately in the `codex_home` Docker volume, using Codex's
file credential store. It survives container restarts. Do not share that volume.
Official sign-in instructions: https://learn.chatgpt.com/docs/auth#login-on-headless-devices

Before your first search, add your CV in **My CV** and set your roles, skills, locations, and sources in **Preferences**. Then choose
**Find opportunities**. Activity appears below the current page; you can browse
while the pipeline runs. The existing prefilters, sources, scoring and drafting
workflow are preserved. A second search retries jobs whose scoring or drafting failed.

## What the dashboard includes

- Opportunities with match score, status, search, pagination and live CSV export.
- Job details, strengths, gaps, original posting link and application drafts.
- Copy drafts and mark shortlisted jobs applied (sets a seven-day follow-up).
- Follow-ups due for applied jobs.
- A form for pasting postings from any job board into the manual inbox.
- A CV editor and preferences for sources, keywords, salary, scoring and AI limits.
- Search activity with start/stop controls. Completed jobs stay saved after stopping.
- Codex connection checks and sign-in guidance.

Jobpipe never sends your applications. Read every draft, verify its claims, and apply
yourself. CV and posting text are sent to the selected AI provider during a search.

## Your data stays in this folder

Docker bind-mounts this folder at `/data`. Existing `jobs.db`, `config.json`, `cv.md`,
`inbox/` and `output/` are used directly and preserved across restarts and rebuilds.
Personal files and secrets are excluded from the Docker build context and image.
Do not run the command-line pipeline alongside a dashboard search.

If upgrading an existing installation, replace only the application files. Keep
your `jobs.db`, `config.json`, `cv.md`, `inbox/` and `output/` intact. The repository ships with blank search preferences and a generic CV template. Your saved preferences, CV, database, OAuth files, inbox, and drafts are ignored by Git.

To back up, stop the app and copy this folder. Store the Codex auth volume separately
only if needed; you can always sign in again instead.

```sh
docker compose stop              # pause; keep data and sign-in
docker compose start             # resume
docker compose logs -f jobpipe   # server diagnostics
docker compose down             # remove container; keep data and sign-in volume
```

Do not use `docker compose down -v` unless you intend to remove the saved Codex login.

The dashboard is bound to your computer's loopback address. It has no shared-user
login and is intended for local personal use. The server checks Host and Origin
and requires same-origin JSON requests for changes. Do not expose it publicly.

## Optional configuration

Copy `.env.example` to `.env` only if you need overrides. For example, to change the
browser port, set `JOBPIPE_PORT=8788`, then restart with `docker compose up -d`.
`TZ` defaults to UTC for follow-up dates inside Docker. Set it to your time zone in `.env` if you prefer.

Codex is the default provider. It uses saved CLI login and your account's Codex
allowance. Setting a model in Preferences overrides the CLI default. Each shortlisted
job needs two AI calls (scoring and drafting); the jobs-per-search limit is not a call
or token limit. One parallel worker is the default. Timeouts apply per AI call.

To use Anthropic instead, set `ANTHROPIC_API_KEY` in `.env`, recreate the container,
then choose Anthropic and an accessible model in Preferences. Its SDK is included
in the image. Environment keys are never returned by the dashboard.

For reproducible builds, set `CODEX_VERSION` to your chosen npm package version in
`.env` before building. The default installs the latest CLI available at build time.

## Run without Docker

Python 3.10+ and Codex CLI are required for the Codex provider:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm install -g @openai/codex
codex login
python server.py
```

On Windows use `.venv\Scripts\activate`. Anthropic is optional outside Docker:
`python -m pip install anthropic`. The server defaults to `127.0.0.1:8787`.
Set `JOBPIPE_DATA_DIR` to use a different local data directory. Missing CV/config
files are initialized from generic templates; existing files are never replaced.

If Python fails before startup with a locale encoding error, try:

```sh
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export PYTHONUTF8=1
python3 server.py
```

Docker sets `C.UTF-8` and `PYTHONUTF8=1` already.

## Existing command-line tools

```sh
python jobpipe.py run
python jobpipe.py list
python jobpipe.py applied <id>
python jobpipe.py followups
python jobpipe.py boards
python jobpipe.py alerts
```

Inside Docker, prepend `docker compose exec jobpipe` to each command. Email-alert
collection remains a command-line feature. It requires `GMAIL_ADDRESS` and
`GMAIL_APP_PASSWORD` in `.env`; output goes to `output/alerts.md`.

## Verification

```sh
python -m unittest discover -s tests -v
node --check web/app.js
docker compose config --quiet
```

The tests cover provider adapters, application drafting and tracking, dashboard
requests, and a search using a simulated Codex executable. They do not make
live job-board or AI provider calls.

## Gmail job alerts

1. In Google Cloud, enable the Gmail API and create a **Desktop app** OAuth client.
   Set up the consent screen and add your Gmail addresses as test users if the app
   is in Testing. Google may expire grants from external apps in Testing after seven days.
2. Download the Desktop client's JSON file and save it as `gmail-client.json`
   in the Jobpipe folder beside `compose.yaml`.
3. Open the local dashboard in your regular browser. Under **Job alerts**, select
   **Connect Gmail** and approve read-only access. Repeat for each account.
4. Choose **Import alerts** or start a search. Jobpipe checks the last 14 days for
   LinkedIn, Glassdoor, Indeed and StepStone alerts. It removes tracking parameters
   from supported posting links and merges copies of the same link across accounts.
   An alert with a single listing and a sufficiently detailed, explicitly labeled
   description enters scoring. For other links, open the posting and paste its
   description into the alert row. Tracking-only and unsupported links are skipped.

Account grants and extracted leads are stored locally under `.gmail/`. Disconnecting
removes the local grant and keeps imported leads. You can revoke Google access from
your Google Account's third-party connections page. Gmail read-only access can read
mailbox contents. Jobpipe limits its searches to the supported job boards and stores
only extracted job information, message IDs and connection details.

[Google OAuth desktop setup](https://developers.google.com/identity/protocols/oauth2/native-app)

## Job sources

Open **Job sources**, paste a public Greenhouse or Lever board URL, and choose
**Preview listings**. **Save source** adds the board to future searches using your
existing location and scoring filters. **Remove** stops future checks. For other
career sites, use **Add a posting** to paste individual job descriptions.

## Markdown and LaTeX CVs

In **My CV**, upload a UTF-8 `.md` or `.tex` file, review it in the editor, and
select **Save CV** to use it in future searches. **Score CV** and **Suggest
improvements** use the configured AI provider on the current editor contents.
Apply individual suggestions to the editor, then save when ready.

LaTeX import supports self-contained documents with common sections, lists,
and resume commands. Jobpipe extracts text without compiling the document.
Custom macros and templates can affect extraction. Job PDFs use the standard
Jobpipe layout and are generated on click. Existing scores and drafts reflect
the CV used when they were generated.

Back up `cv-source.json` with your other Jobpipe data once you save an active
CV from the editor. Older installations use `cv.md` until the first save.

## Focus your searches

Set job title phrases, skills, locations, and sponsorship phrases in **Preferences**.
Title phrases restrict the roles considered when provided. The local relevance
cutoff favors skills in titles and requirements over general mentions. A cutoff
of 4 is the default. Location, relocation signals, and posting date break ties.
You can choose whether to include unlisted locations or consider jobs outside
your locations when a relocation phrase matches.

**Jobs per search** caps AI scoring after local ranking. A search can score fewer
jobs if too few clear the cutoff. Unscored jobs that still appear in their sources
can compete with newer matches next time. The activity panel shows the current
search's found, passed filters, sent to AI, and shortlisted counts.
