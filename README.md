# BrandSentinel (Team: Provenance Pair)

Pre-publication brand governance: checks content against approved guidelines, facts and terminology, explains findings with their source, suggests fixes, and routes content through human review and approval. AI suggests; humans decide.

## Requirements

- Python 3.10 or later
- Node.js and npm
- An Anthropic API key is optional; deterministic review runs without it

## Backend setup

In PowerShell, from the project root:

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create named accounts locally. Choose a role for each account; the password is entered at a hidden prompt and must be at least 12 characters. Run this once for each person/role you need:

```powershell
python main.py create-user --name admin --role admin
python main.py create-user --name creator --role creator
python main.py create-user --name manager --role manager
python main.py create-user --name reviewer --role reviewer
```

Roles are fixed on the server and cannot be selected or changed from the login screen. No demo usernames or passwords are preconfigured. The existing database had no user accounts; create your own credentials with the commands above.

Seed the sample sources. This command is safe to repeat: existing equivalent sources are left as-is, including sources subsequently edited by an administrator.

```powershell
python main.py seed-demo
```

Start the backend, from the `backend` directory:

```powershell
python -m uvicorn main:app --reload
```

The API is at `http://localhost:8000`; interactive API documentation is at `http://localhost:8000/docs`. SQLite schema initialization and non-destructive migrations run automatically when the backend starts.

## Frontend setup

Open a second PowerShell window from the project root:

```powershell
Set-Location frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm.cmd install
npm.cmd run dev
```

Open the local Vite URL printed by npm. The default API URL is `http://localhost:8000`. To use a different backend, set `VITE_API_URL` in `frontend\.env` before starting Vite. Never put an Anthropic key in a `VITE_` variable or frontend file.

## Database

The default SQLite database is:

```text
backend\brand.db
```

The path is anchored to the backend directory, independent of the current working directory. Set the backend process environment variable `DB_PATH` to use a different database file. Existing records are kept; startup creates missing tables and adds missing columns without dropping or recreating tables.

The database contains `users`, `sources`, `submissions`, `findings`, `versions`, `comments`, and `approval_activity`. Suggested revisions are stored on their finding records; there is no separate suggestions table. To inspect it with [DB Browser for SQLite](https://sqlitebrowser.org/):

1. Choose **Open Database** and select `backend\brand.db`.
2. Use **Browse Data** to inspect tables and records.
3. Use **Execute SQL** for queries such as:

```sql
SELECT id, kind, title, body, created_by FROM sources ORDER BY id;
SELECT id, title, author, status, version, llm_status FROM submissions ORDER BY id;
SELECT id, submission_id, version, ftype, severity, snippet, why,
       source_id, origin, status
FROM findings
ORDER BY submission_id, version, id;
SELECT * FROM approval_activity ORDER BY id;
```

Close the database in DB Browser before inspecting changes made by the running backend if the viewer has not refreshed its view.

## Sample review

Log in with the accounts you created above. An administrator can manage brand sources; a creator can select **Load sample post** and then **Review content**:

**Title:** `Summer Promotion Ad`  
**Channel:** `social post`

```text
Our app is the #1 fastest app in Bangladesh!!! We guarantee that every customer will save 90% on all purchases. Get cheap plans for everyone.
```

Review results include deterministic/LLM origin, matched text, reason, severity, confidence, and the retrieved source where available. An unsupported claim can cite a guideline explaining the verification requirement; a conflicting savings guarantee can cite the approved fact that savings vary and are not guaranteed. A cited source is context, not proof that the promotional claim is true. A finding without a relevant source is shown as needing human review.

Creators can accept or reject suggestions, edit content into a new version, comment, and send their submission for review. Managers, reviewers, and admins can approve, request changes, or reject. Approval with unresolved high-severity findings requires a written reason; the decision and reason are stored in approval activity.

## Optional Anthropic review

The API key is read only by the backend from `ANTHROPIC_API_KEY`. For a PowerShell session, enter it without echoing the value:

```powershell
$secret = Read-Host "Anthropic API key" -AsSecureString
$env:ANTHROPIC_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
```

Then start the backend in that same PowerShell session. The optional model can be selected with the backend-only `ANTHROPIC_MODEL` environment variable; by default the backend uses `claude-haiku-4-5`. Configure secrets through your hosting provider's secret manager in deployment. Do not commit a key, place it in `frontend\.env`, or expose it through a `VITE_` variable.

When no key is configured, deterministic checks still run and the review explicitly reports that LLM review was skipped. With a key, only keyword-retrieved brand sources and the submission text are sent to Anthropic. The response must be valid JSON, cite a retrieved source ID, and quote text that appears verbatim in the submission. Invalid citations/quotes are discarded; API, timeout, rate-limit, and response errors are logged without logging the key and are reported as an LLM review failure. LLM findings are labelled separately and are not treated as evidence that a claim is true.

## Tests and build

From the project root:

```powershell
Set-Location backend
python -m unittest discover -s tests -v
Set-Location ..\frontend
npm.cmd run build
```

The backend tests use temporary databases and mocked Anthropic responses; no real API key or API call is needed. The frontend command runs the Vite production build.

## Known limitations

- Source retrieval uses keyword overlap, not embeddings; relevant context may be missed.
- User and role administration is performed locally with the backend CLI; there is no user-management screen, password reset flow, or self-registration.
- Login tokens are kept in backend memory and expire after 12 hours; restarting the backend invalidates active sessions.
- This is a local/demo governance workflow, not a substitute for a production identity provider, deployment-specific CORS configuration, or legal review.
- Visual/image review is not implemented.

## Deploy

Deploy the FastAPI service from `backend` with:

```text
python -m uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set a persistent, protected `DB_PATH` if the platform's local filesystem is ephemeral, provision accounts as part of a secure deployment process, and configure `ANTHROPIC_API_KEY` only as an optional backend secret. Deploy the React/Vite app from `frontend` and set `VITE_API_URL` to the backend URL. Configure CORS to the deployed frontend origin before public deployment.
