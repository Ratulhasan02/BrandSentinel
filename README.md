# BrandSentinel

Pre-publication brand governance with explainable AI and human control.

BrandSentinel checks content against a brand's approved guidelines, facts and terminology before it is published. It explains every finding, shows the source involved, suggests a correction, and routes the content through a human review and approval workflow. AI suggests; humans decide.

Built by Team Provenance Pair for the Inkloom AI hackathon (Problem: AI brand-governance platform).

## Live project

| | Link |

|---|---|

| Live app (frontend) | https://brand-sentinel-six.vercel.app/ |

| Backend API (docs at `/docs`, status at `/health`) | https://brandsentinel-8ebf.onrender.com |

| Source code | https://github.com/Ratulhasan02/BrandSentinel |

> Free hosting note: the backend sleeps when idle, so the first request can take up to a minute. The login page shows a "waking up" message and retries automatically; please wait.

## Demo accounts (one click)

The login page has a Judge demo accounts box with one button per role. You can also type the credentials yourself. These accounts are for evaluation only and will be removed after the hackathon.

| Role | Username | Password | What to try |

|---|---|---|---|

| Creator | `creator_demo` | `Provenance@2026` | Opens a draft sample: accept or reject suggestions, then send it for review |

| Reviewer | `reviewer_demo` | `Provenance@2026` | Opens a sample waiting for review: comment, approve, request changes or reject |

| Manager | `manager_demo` | `Provenance@2026` | Same review decisions as reviewer |

| Admin | `admin_demo` | `Provenance@2026` | Users page, Brand sources, and Reset demo samples |

Two sample submissions are loaded automatically: a risky promotional post waiting for review, and a short draft to practise accepting and rejecting suggestions. If a judge approves or edits them, the admin's Reset demo samples button restores both. You can also click Create account to sign up yourself.

## The problem

Organisations publish through many employees, agencies and AI tools. Nobody sees everything, so wrong claims, outdated facts, off-brand language and inaccessible visuals reach the public before anyone notices. Brand guidelines live in long documents that cannot check anything, manual review is slow and inconsistent, and generic AI tools do not know what the brand has officially approved and can invent claims.

## Our solution

A review loop that sits between "content written" and "content published":
1. An admin maintains the source of truth: guidelines, approved facts and terminology.
2. A creator submits content (pasted text, `.txt` or `.docx`).
3. The system produces evidence-backed findings: what was flagged, why, how severe, how confident, and which approved source is involved.
4. The creator accepts or rejects each suggestion. Nothing is ever changed automatically.
5. Managers, reviewers and admins comment, approve, request changes or reject. Every step is recorded.
Design principles: evidence first, suggest never override, human final say, confidential by design, honest about uncertainty (an unsupported claim is labelled "needs human check", never guessed).

## Hackathon progress

| Round | Goal | Status |

|---|---|---|

| Round 1: The Plan | Problem, users, solution, workflow, stack, responsible design, plan | Submitted (plan PDF) |

| Round 2: The Build | Core workflow working end to end, deployed | This repository (see "Completed in Round 2") |

| Round 3: The Finish | Three major improvements, reliability, documentation | Planned (see "Round 3 roadmap") |

### Completed in Round 2
- Accounts and roles: username and password login, passwords hashed with PBKDF2-SHA256, 12-hour sessions. Sign-up lets users choose Creator, Reviewer or Manager. Creator and reviewer accounts are active immediately; manager accounts wait for administrator approval before they can log in. Admin accounts are never self-created.
- Admin Users page: approve pending manager sign-ups and change roles (admin and demo accounts are protected).
- Source library: admins add guidelines, approved facts and banned-to-preferred terminology.
- Content intake: paste text or upload `.txt` / `.docx`; channel selection; one-click sample post.
- Automated review: terminology, tone (shouting, repeated exclamation marks) and unsupported or conflicting promotional claims, checked against the approved sources. Optional LLM pass for tone, messaging and claims.
- Explainable findings: highlighted text, reason, severity, confidence, origin (deterministic or LLM) and the cited source. Findings with no relevant source are shown as needing human review.
- Human control: accept or reject each suggestion (accepting creates a new version); manual editing as a new version; comments; approve / request changes / reject; approving with unresolved high-severity findings requires a written reason; approved and rejected submissions are locked.
- Audit trail: revision history and approval activity (who, when, what, why).
- Transparency: an AI-use notice on the submission form and a per-review status showing whether the LLM pass completed, was skipped or failed.
- Judge-ready demo mode: one-click demo accounts for every role, pre-loaded sample submissions, an admin reset button, a `/health` status endpoint, and a login page that waits and retries while the free server wakes up.
### Changes from the Round 1 plan

| Planned | What we did and why |

|---|---|

| PostgreSQL + pgvector | SQLite and keyword retrieval, to reach a reliable end-to-end workflow first. Embedding retrieval is part of Round 3. |

| JWT login | Username/password login with in-memory expiring tokens. SSO and password reset are future work. |

| DOCX, PDF and image intake | Text and DOCX done. PDF and image intake move to Round 3 with visual review. |

| React + FastAPI + hosted LLM | Implemented as planned. |

## Round 3 roadmap

We will deliver three substantial additions. None of these exist yet.
1. Evidence-verified findings. Embedding-based retrieval of sources, a stricter validator that checks that every finding's quote exists in the cited source, calibrated confidence, and a seeded-error test set (at least 50 items) to report precision, recall and false-positive rate before and after.
2. Visual and accessibility review. Image and PDF intake; colour palette and WCAG contrast checks, missing alt-text detection, logo-usage and readability checks, reported in the same explainable finding format.
3. Governance insights with clarity detection. A dashboard of recurring violation types, topics and authors, reviewer override rates, and automatic flagging of guidelines that reviewers often override or dispute, so admins can fix unclear rules.
Also planned: reliability fixes from user testing, a demo video, and a privacy, security and accessibility statement.

## How a review works

```

content -> extract text -> rule checks + retrieve relevant approved sources

        -> optional LLM review -> validate and de-duplicate

        -> findings (with source IDs) -> creator decisions

        -> manager / reviewer approval -> audit trail

```
- Rules first, AI second. Anything that can be checked exactly (banned terms, shouting, claim keywords) is done by code: fast, reproducible, fully explainable.
- Grounding guard for the LLM. An LLM finding is kept only if its quote appears verbatim in the content and it cites a source ID that was actually retrieved. Anything else is discarded.
- A cited source is context, not proof. Citing a guideline does not mean a promotional claim is true; unsupported claims remain flagged for human verification.
## Roles and permissions

| Role | What they can do |

|---|---|

| Creator | Submit content; accept/reject findings, edit and send their own submissions for review; comment on their own submissions |

| Reviewer | See all submissions; comment; approve, request changes or reject content in review |

| Manager | Same as reviewer (requires admin approval at sign-up) |

| Admin | Everything above, plus manage brand sources and users (approve managers, change roles) |

## Tech stack

| Layer | Technology |

|---|---|

| Frontend | React 18, Vite |

| Backend | Python 3.10+, FastAPI, Uvicorn |

| Database | SQLite (schema created and migrated automatically at startup) |

| AI (optional) | Anthropic Claude API, JSON-only structured output; default model `claude-haiku-4-5` |

| Parsing | python-docx for `.docx` |

| Security | PBKDF2-SHA256 password hashing, token sessions, role and ownership checks on every endpoint |

| Hosting | Vercel (frontend), Render (backend) |

## Quick start for judges
1. Open https://brand-sentinel-six.vercel.app/ (free hosting: the first load can take up to a minute).
2. In the Judge demo accounts box click Use (creator). A draft sample opens with findings (reason, severity, confidence, source). Accept or reject suggestions; accepting creates a new version. Click Send to manager review.
3. Log out and click Use (reviewer) or Use (manager). A sample waiting for review opens. Read the findings, add a comment, then approve, request changes or reject. Approving with an unresolved high-severity finding needs a written reason.
4. Click Use (admin) to open the Users page (approve pending manager sign-ups, change roles), Brand sources, and Reset demo samples.
5. Optional: click Create account to sign up as creator or reviewer, or Load sample post to review your own text.
## Sample review

Title: `Summer Promotion Ad` Channel: `social post`

```text

Our app is the #1 fastest app in Bangladesh!!! We guarantee that every customer will save 90% on all purchases. Get cheap plans for everyone.

```

Expected: an unsupported ranking claim, a conflicting savings guarantee (high severity, citing the approved fact that savings vary), a tone finding for the repeated exclamation marks, and a terminology finding for "cheap plans" with the suggestion "affordable plans".

## Run locally

Requirements: Python 3.10+, Node.js and npm. An Anthropic API key is optional; deterministic review works without it.

### Backend (PowerShell, from the project root)

```powershell

Set-Location backend

python -m venv .venv

..venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt

```

Option 1, demo mode (same one-click accounts and samples as the live demo). Set the variables in the same window that runs the server, and restart the server after changing them:

```powershell

Env: Demo Mode = "true"

Env: Demo Password = "Provenance@2026"

python -m uvicorn main:app --reload

```

Option 2, your own accounts (hidden password prompt, at least 12 characters; admin accounts can only be created this way):

```powershell

python main.py create-user --name admin --role admin

python main.py create-user --name creator --role creator

python main.py create-user --name manager --role manager

python main.py create-user --name reviewer --role reviewer

python main.py seed-demo

python -m uvicorn main:app --reload

```

`seed-demo` adds the sample brand sources and is safe to repeat. API: `http://localhost:8000\`, interactive docs: `http://localhost:8000/docs\`, status: `http://localhost:8000/health\` (shows whether demo mode is on).

### Frontend (second PowerShell window)

```powershell

Set-Location frontend

if (-not (Test-Path .env)) { Copy-Item .env.example .env }

npm.cmd install

npm.cmd run dev

```

Open the Vite URL printed by npm. The default API URL is `http://localhost:8000\`. If `frontend.env` sets `VITE_API_URL` to the deployed backend, the local frontend will talk to that backend instead; change it back to `http://localhost:8000\` and restart `npm.cmd run dev`. Never put an Anthropic key in a `VITE_` variable or any frontend file.

### Sign-up and approval

Public sign-up (`POST /register`) lets users choose creator, reviewer or manager and closes at 500 users. Creator and reviewer accounts are active immediately. Manager accounts are created as pending and cannot log in until an admin approves them (Approve manager on the Users page, or `POST /users/{user_id}/approve`). Changing a user's role as an admin also activates the account.

### Demo mode

Demo mode is controlled by backend environment variables, not by the code, so it is off unless you turn it on. The live judging deployment has it on.

| Variable | Meaning |

|---|---|

| `DEMO_MODE=true` | On startup, create `creator_demo`, `reviewer_demo`, `manager_demo`, `admin_demo`, the sample brand sources and the two sample submissions (no AI call is made while seeding). Expose the credentials through `GET /demo-accounts` so the login page can show its one-click box. Enable `POST /demo/reset` for admins. |

| `DEMO_PASSWORD` | Shared demo password, at least 12 characters (the server will not start with a shorter one). |

With demo mode off, startup removes the demo accounts and their sample submissions and `/demo-accounts` returns an empty list. Do not enable demo mode on a deployment that holds real data.

## Optional Anthropic review

The key is read only by the backend from `ANTHROPIC_API_KEY`. In PowerShell, without echoing it:

```powershell

$secret = Read-Host "Anthropic API key" -AsSecureString

Env: Anthropic API Key = [System.Net.NetworkCredential]::new("", $secret).Password

```

Start the backend in that same session. Choose another model with `ANTHROPIC_MODEL` (default `claude-haiku-4-5`). In deployment, use the host's secret manager; never commit a key.

With no key, deterministic checks still run and the review reports that the LLM pass was skipped. With a key, only the keyword-retrieved brand sources and the submission text are sent to Anthropic. The response must be valid JSON, cite a retrieved source ID and quote text that appears verbatim in the submission; invalid items are discarded. API, timeout and parsing errors are logged without the key and shown as "LLM review failed". LLM findings are labelled separately.

## Database

Default file: `backend\brand.db` (anchored to the backend folder, not committed to Git). Set `DB_PATH` to use another file. Startup creates missing tables and adds missing columns without dropping data.

Tables: `users`, `sources`, `submissions`, `findings`, `versions`, `comments`, `approval_activity`. Suggested revisions are stored on their finding records. To inspect with [DB Browser for SQLite](https://sqlitebrowser.org/), open `backend\brand.db` and use Browse Data or Execute SQL, for example:

```sql

SELECT id, kind, title, body, created_by FROM sources ORDER BY id;

SELECT id, title, author, status, version, llm_status FROM submissions ORDER BY id;

SELECT id, submission_id, version, ftype, severity, snippet, why, source_id, origin, status

FROM findings ORDER BY submission_id, version, id;

SELECT * FROM approval_activity ORDER BY id;

```

## API overview

| Endpoint | Purpose |

|---|---|

| `GET /health` | Server status and whether demo mode is on (no user data) |

| `POST /login`, `POST /register` | Authentication; sign-up with role choice |

| `GET /demo-accounts`, `POST /demo/reset` | Demo mode only: demo credentials; admin resets the sample submissions |

| `GET /users`, `POST /users/{id}/approve`, `POST /users/{id}/role` | Admin: user list, approve pending managers, change roles |

| `GET /sources`, `POST /sources` | Read sources; admin adds sources |

| `POST /extract` | Extract text from `.txt` / `.docx` |

| `GET /submissions`, `POST /submissions` | List (creators see their own) and create submissions |

| `GET /submissions/{id}`, `PUT /submissions/{id}` | Detail with findings, comments, versions and activity; manual edit as new version |

| `POST /submissions/{id}/rereview`, `/comments`, `/status` | Re-run review, comment, change status |

| `POST /findings/{id}/decision` | Accept or reject a suggestion |

## Tests and build

```powershell

Set-Location backend

python -m unittest discover -s tests -v

Set-Location ..\frontend

npm.cmd run build

```

Run the tests from the `backend` folder with the virtual environment active. The 20 backend unit tests use temporary databases and mocked Anthropic responses, so no API key or network call is needed; they cover review logic, LLM validation, sign-up and approval, role access, demo mode and the demo reset. The frontend command runs the Vite production build. The deployed project was also tried end to end by two people, who reported that the core workflow worked as expected.

## Responsible AI, privacy and security
- Human control: suggestions are never applied automatically; every decision and override is recorded with who and when.
- Disclosure: an AI-use notice appears on the submission form; each review states whether the LLM pass ran.
- Confidentiality: with no key configured, no content leaves the server. With a key, only the submission text and the retrieved brand sources are sent to Anthropic. The key never reaches the browser.
- Access control: role and ownership checks on every endpoint; creators only see their own submissions; admin accounts cannot be self-created; passwords are hashed and never stored in plain text.
## Known limitations
- Source retrieval uses keyword overlap, not embeddings, so relevant context can be missed.
- Claim detection relies on a keyword and pattern list.
- Login tokens are kept in backend memory (12-hour expiry); restarting the backend signs everyone out.
- On free hosting the filesystem can reset, which resets the SQLite database (demo accounts and samples are recreated automatically while demo mode is on). Use a persistent `DB_PATH` for anything beyond a demo.
- The judging deployment exposes shared demo accounts (including an admin) with public credentials, for evaluation only; do not enter real data there. They will be removed after the hackathon.
- Reviewer sign-up is self-serve. Pending manager requests can be approved but not rejected from the UI. No email verification or password reset.
- Image and PDF review are not implemented yet (Round 3).
- This is a demo governance workflow, not a replacement for a production identity provider, deployment-specific CORS configuration or legal review.
## Deploy

Backend (Render or similar), root `backend`:

```text

python -m uvicorn main:app --host 0.0.0.0 --port $PORT

```

Environment variables: `DEMO_MODE=true` and `DEMO_PASSWORD` (12+ characters) for the judging demo; `ANTHROPIC_API_KEY` only as an optional secret. After the hackathon remove `DEMO_MODE` and redeploy to delete the demo accounts and samples. For a real deployment set a persistent, protected `DB_PATH`, create admin accounts through a secure process, and restrict CORS to the frontend origin.

Frontend (Vercel or similar)

 root `frontend`: set `VITE_API_URL` to the backend URL (redeploy after changing it).

## AI assistance and disclosure

This project was built with AI assistance (Claude) for code generation, review and documentation; the team reviewed and tested the result. External services at runtime: Anthropic API (optional, backend only). Open-source libraries: FastAPI, Uvicorn, python-docx, React, Vite (see `requirements.txt` and `package.json`). No external datasets or UI templates were used; the sample brand sources and submissions are small examples written by the team.

## Team

Provenance Pair:

Ratul Hasan (team lead),

Jamil Sarker Hamim.

Uttara University

Dhaka, Bangladesh.

Individual contributions are listed in the submitted project PDF.