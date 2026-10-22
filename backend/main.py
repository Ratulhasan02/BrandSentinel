import argparse
import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
_configured_db = Path(os.getenv("DB_PATH", str(BASE_DIR / "brand.db")))
DB = _configured_db if _configured_db.is_absolute() else BASE_DIR / _configured_db
ROLES = {"creator", "manager", "reviewer", "admin"}
TOKEN_TTL_SECONDS = 60 * 60 * 12
PASSWORD_ITERATIONS = 310_000
logger = logging.getLogger("brandsentinel")
TOKENS: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(_app):
    init()
    yield


app = FastAPI(title="BrandSentinel API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def q(sql, args=(), one=False, write=False):
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(sql, args)
        rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
        if write:
            connection.commit()
        if write:
            return cursor.lastrowid
        return (rows[0] if rows else None) if one else rows
    finally:
        connection.close()


def init():
    statements = [
        """CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, role TEXT NOT NULL,
            password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
            created TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sources(
            id INTEGER PRIMARY KEY, kind TEXT, title TEXT, body TEXT,
            banned TEXT, preferred TEXT)""",
        """CREATE TABLE IF NOT EXISTS submissions(
            id INTEGER PRIMARY KEY, title TEXT, channel TEXT, author TEXT,
            status TEXT, text TEXT, version INT, created TEXT)""",
        """CREATE TABLE IF NOT EXISTS versions(
            id INTEGER PRIMARY KEY, submission_id INT, version INT, text TEXT,
            note TEXT, author TEXT, created TEXT)""",
        """CREATE TABLE IF NOT EXISTS findings(
            id INTEGER PRIMARY KEY, submission_id INT, version INT, ftype TEXT,
            severity TEXT, s_from INT, s_to INT, snippet TEXT, why TEXT,
            source_id INT, suggestion TEXT, confidence REAL, status TEXT)""",
        """CREATE TABLE IF NOT EXISTS comments(
            id INTEGER PRIMARY KEY, submission_id INT, author TEXT, role TEXT,
            body TEXT, created TEXT)""",
        """CREATE TABLE IF NOT EXISTS approval_activity(
            id INTEGER PRIMARY KEY, submission_id INT NOT NULL, status TEXT NOT NULL,
            actor TEXT NOT NULL, role TEXT NOT NULL, reason TEXT NOT NULL,
            created TEXT NOT NULL)""",
    ]
    for statement in statements:
        q(statement, write=True)
    _add_column("sources", "created_by", "TEXT")
    _add_column("submissions", "llm_status", "TEXT NOT NULL DEFAULT 'not_run'")
    _add_column("submissions", "llm_detail", "TEXT NOT NULL DEFAULT ''")
    _add_column("findings", "origin", "TEXT NOT NULL DEFAULT 'deterministic'")
    q(
        "CREATE INDEX IF NOT EXISTS idx_findings_submission_version "
        "ON findings(submission_id, version)",
        write=True,
    )
    q(
        "CREATE INDEX IF NOT EXISTS idx_versions_submission "
        "ON versions(submission_id, version)",
        write=True,
    )


def _add_column(table, column, declaration):
    existing = {row["name"] for row in q(f"PRAGMA table_info({table})")}
    if column not in existing:
        q(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}", write=True)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _password_fields(password):
    if len(password) < 12:
        raise ValueError("Passwords must be at least 12 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS
    ).hex()
    return digest, salt


def create_user(name, role, password):
    name = name.strip()
    if not name or role not in ROLES:
        raise ValueError("A non-empty name and valid role are required.")
    password_hash, password_salt = _password_fields(password)
    try:
        return q(
            "INSERT INTO users(name,role,password_hash,password_salt,created) "
            "VALUES(?,?,?,?,?)",
            (name, role, password_hash, password_salt, now()),
            write=True,
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"A user named '{name}' already exists.") from exc


def me(token):
    session = TOKENS.get(token)
    if not session or session["expires"] <= datetime.now(timezone.utc).timestamp():
        TOKENS.pop(token, None)
        raise HTTPException(401, "Please log in")
    return session


def require_submission_access(submission, user, *, owner_can_access=True):
    if user["role"] in ("admin", "manager", "reviewer"):
        return
    if owner_can_access and submission["author"] == user["name"]:
        return
    raise HTTPException(403, "You cannot access this submission")


def words(text):
    return set(re.findall(r"[a-z]{3,}", text.lower()))


def retrieve(text, kinds=("guideline", "fact", "term"), k=6):
    target = words(text)
    scored = []
    for source in q(
        "SELECT * FROM sources WHERE kind IN (%s)" % ",".join("?" * len(kinds)),
        kinds,
    ):
        overlap = len(target & words(f"{source['title']} {source['body']}"))
        if source["kind"] == "term":
            overlap += len(target & words(f"{source['banned']} {source['preferred']}"))
        if overlap:
            scored.append((overlap, source))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [source for _, source in scored[:k]]


CLAIM = re.compile(
    r"#\s*1(?!\d)(?:\s+(?:fastest|best))?|\bnumber\s+one\b|"
    r"\b(best|fastest|guarantee(?:d)?|"
    r"100\s*%|risk[- ]free|never fails)\b|"
    r"\b(?:save|saves|saved|saving|savings)\b[^.!?\n]{0,50}\b\d+(?:\.\d+)?\s*%",
    re.IGNORECASE,
)
TONE = re.compile(r"!{2,}|\b[A-Z]{4,}\b")


def _claim_source(sentence, claim):
    claim_text = claim.group().lower()
    if re.search(r"save|saving|savings|guarantee|%", claim_text):
        facts = retrieve(sentence, ("fact",), k=10)
        explicit = [
            source
            for source in facts
            if re.search(
                r"sav(?:e|es|ed|ing|ings)|guarantee|discount|price|percent|%",
                source["body"],
                re.IGNORECASE,
            )
        ]
        if explicit:
            return explicit[0]
    if re.search(r"#\s*1|number\s+one|best|fastest", claim_text):
        superlative_guideline = next(
            (
                source
                for source in q("SELECT * FROM sources WHERE kind='guideline'")
                if re.search(
                    r"superlative|ranking|number one|fastest|best",
                    source["title"] + " " + source["body"],
                    re.IGNORECASE,
                )
            ),
            None,
        )
        if superlative_guideline:
            return superlative_guideline
    guidelines = retrieve(sentence, ("guideline",), k=10)
    return next(
        (
            source
            for source in guidelines
            if re.search(
                r"claim|superlative|guarantee|misleading|evidence",
                source["title"] + " " + source["body"],
                re.IGNORECASE,
            )
        ),
        guidelines[0] if guidelines else None,
    )


def rule_review(text):
    findings = []
    terminology = []
    for source in q("SELECT * FROM sources WHERE kind='term'"):
        banned = (source["banned"] or "").strip()
        if not banned:
            continue
        for match in re.finditer(r"\b%s\b" % re.escape(banned), text, re.IGNORECASE):
            terminology.append(
                dict(
                    ftype="terminology",
                    severity="medium",
                    s_from=match.start(),
                    s_to=match.end(),
                    snippet=match.group(),
                    why=(
                        f"'{match.group()}' is not approved wording. "
                        f"Preferred term: '{source['preferred']}'."
                    ),
                    source_id=source["id"],
                    suggestion=source["preferred"] or "",
                    confidence=0.95,
                    origin="deterministic",
                )
            )
    terminology.sort(key=lambda item: (item["s_from"], -(item["s_to"] - item["s_from"])))
    for finding in terminology:
        if any(
            finding["s_from"] < prior["s_to"]
            and prior["s_from"] < finding["s_to"]
            for prior in findings
        ):
            continue
        findings.append(finding)

    tone_sources = q("SELECT * FROM sources WHERE kind='guideline'")
    tone_source = next(
        (
            source
            for source in tone_sources
            if re.search(
                r"tone|professional|clear|exclamation",
                source["title"] + " " + source["body"],
                re.IGNORECASE,
            )
        ),
        None,
    )
    for match in TONE.finditer(text):
        findings.append(
            dict(
                ftype="tone",
                severity="low",
                s_from=match.start(),
                s_to=match.end(),
                snippet=match.group(),
                why="Shouting or repeated exclamation marks conflict with the professional tone guideline.",
                source_id=tone_source["id"] if tone_source else None,
                suggestion="!" if match.group().startswith("!") else match.group().capitalize(),
                confidence=0.8,
                origin="deterministic",
            )
        )

    for sentence_match in re.finditer(r"[^.!?\n]+[.!?]?", text):
        sentence = sentence_match.group()
        claims = list(CLAIM.finditer(sentence))
        if not claims:
            continue
        first_claim, last_claim = claims[0], claims[-1]
        snippet = sentence[first_claim.start() : last_claim.end()]
        evidence_claim = next(
            (
                claim
                for claim in claims
                if re.search(r"save|saving|savings|guarantee|%", claim.group(), re.IGNORECASE)
            ),
            first_claim,
        )
        source = _claim_source(sentence, evidence_claim)
        source_is_fact = source is not None and source["kind"] == "fact"
        high_risk = bool(
            any(
                re.search(
                    r"guarantee|save|saving|savings|%",
                    claim.group(),
                    re.IGNORECASE,
                )
                for claim in claims
            )
        )
        reason = (
            f"Claim '{snippet}' conflicts with the approved fact: {source['body']}"
            if source_is_fact
            else f"Unsupported promotional claim ('{snippet}'): no approved fact supports it; human verification is required."
        )
        start = sentence_match.start() + first_claim.start()
        findings.append(
            dict(
                ftype="claim",
                severity="high" if high_risk else "medium",
                s_from=start,
                s_to=start + len(snippet),
                snippet=snippet,
                why=reason,
                source_id=source["id"] if source else None,
                suggestion="",
                confidence=0.9 if source_is_fact else 0.8,
                origin="deterministic",
            )
        )
    return findings


def _validated_llm_findings(text, content, retrieved):
    if not content or not isinstance(content, str):
        raise ValueError("The response did not contain JSON text.")
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content)
    items = json.loads(cleaned)
    if not isinstance(items, list):
        raise ValueError("The response must be a JSON list.")
    retrieved_ids = {source["id"] for source in retrieved}
    findings = []
    for item in items:
        if not isinstance(item, dict):
            continue
        quote = item.get("quote")
        why = item.get("why")
        source_id = item.get("source_id")
        kind = item.get("type")
        suggestion = item.get("suggestion", "")
        confidence = item.get("confidence", 0.6)
        if (
            not isinstance(quote, str)
            or not quote
            or quote not in text
            or not isinstance(why, str)
            or not why.strip()
            or isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or source_id not in retrieved_ids
            or kind not in {"tone", "messaging", "claim"}
            or not isinstance(suggestion, str)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            continue
        start = text.find(quote)
        findings.append(
            dict(
                ftype=kind,
                severity="medium",
                s_from=start,
                s_to=start + len(quote),
                snippet=quote,
                why=why.strip(),
                source_id=source_id,
                suggestion=suggestion,
                confidence=float(confidence),
                origin="llm",
            )
        )
    return findings


def llm_review(text):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return [], "skipped", "ANTHROPIC_API_KEY is not configured."
    retrieved = retrieve(text, k=6)
    if not retrieved:
        return [], "skipped", "No relevant brand sources were retrieved."
    try:
        import anthropic

        model = os.getenv(
            "ANTHROPIC_MODEL", os.getenv("LLM_MODEL", "claude-haiku-4-5")
        )
        client = anthropic.Anthropic(api_key=key, timeout=20, max_retries=0)
        context = "\n".join(
            f"[{source['id']}] {source['title']}: {source['body']}"
            for source in retrieved
        )
        response = client.messages.create(
            model=model,
            max_tokens=1200,
            system=(
                "Review the submitted content for tone, messaging, and potentially "
                "misleading claims. The sources are guidance, not proof that a claim "
                "is true. Return only a JSON array. Each item must have quote "
                "(exact substring), type (tone|messaging|claim), why, source_id "
                "(one of the supplied IDs), suggestion (string), and confidence "
                "(number from 0 to 1). Never invent a citation; return [] if there "
                "is no source-grounded issue."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"SOURCES:\n{context}\n\nCONTENT:\n{text}",
                }
            ],
        )
        content = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        return _validated_llm_findings(text, content, retrieved), "completed", ""
    except Exception as exc:
        logger.warning("Anthropic review failed (%s).", type(exc).__name__)
        return [], "failed", f"Anthropic review failed ({type(exc).__name__})."


def run_review(submission_id):
    submission = q(
        "SELECT * FROM submissions WHERE id=?", (submission_id,), one=True
    )
    if not submission:
        raise HTTPException(404, "Submission not found")
    q(
        "DELETE FROM findings WHERE submission_id=? AND version=? AND status='pending'",
        (submission_id, submission["version"]),
        write=True,
    )
    rejected = {
        (row["snippet"], row["ftype"])
        for row in q(
            "SELECT snippet,ftype FROM findings WHERE submission_id=? AND status='rejected'",
            (submission_id,),
        )
    }
    deterministic = rule_review(submission["text"])
    llm_findings, llm_status, llm_detail = llm_review(submission["text"])
    q(
        "UPDATE submissions SET llm_status=?, llm_detail=? WHERE id=?",
        (llm_status, llm_detail, submission_id),
        write=True,
    )
    accepted_ranges = []
    for finding in sorted(
        deterministic + llm_findings, key=lambda item: (item["s_from"], item["s_to"])
    ):
        if (finding["snippet"], finding["ftype"]) in rejected:
            continue
        if any(
            finding["s_from"] < end and start < finding["s_to"]
            for start, end in accepted_ranges
        ):
            continue
        accepted_ranges.append((finding["s_from"], finding["s_to"]))
        q(
            """INSERT INTO findings(
                submission_id,version,ftype,severity,s_from,s_to,snippet,why,
                source_id,suggestion,confidence,status,origin
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending',?)""",
            (
                submission_id,
                submission["version"],
                finding["ftype"],
                finding["severity"],
                finding["s_from"],
                finding["s_to"],
                finding["snippet"],
                finding["why"],
                finding["source_id"],
                finding["suggestion"],
                finding["confidence"],
                finding["origin"],
            ),
            write=True,
        )
    return {"llm_status": llm_status, "llm_detail": llm_detail}


class Login(BaseModel):
    name: str
    password: str


class NewSub(BaseModel):
    title: str
    channel: str = "social post"
    text: str


class EditSub(BaseModel):
    title: str
    channel: str
    text: str
    note: str = "Manual edit"


class Decision(BaseModel):
    decision: Literal["accepted", "rejected"]


class Comment(BaseModel):
    body: str


class Status(BaseModel):
    status: Literal["in_review", "approved", "changes_requested", "rejected"]
    reason: str = ""


class Source(BaseModel):
    kind: Literal["guideline", "fact", "term"]
    title: str
    body: str
    banned: str = ""
    preferred: str = ""


@app.post("/login")
def login(body: Login):
    user = q("SELECT * FROM users WHERE name=?", (body.name.strip(),), one=True)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        body.password.encode("utf-8"),
        bytes.fromhex(user["password_salt"]),
        PASSWORD_ITERATIONS,
    ).hex()
    if not hmac.compare_digest(candidate, user["password_hash"]):
        raise HTTPException(401, "Invalid username or password")
    token = secrets.token_urlsafe(32)
    TOKENS[token] = {
        "name": user["name"],
        "role": user["role"],
        "expires": datetime.now(timezone.utc).timestamp() + TOKEN_TTL_SECONDS,
    }
    return {"token": token, "name": user["name"], "role": user["role"]}


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    data = await file.read()
    if file.filename and file.filename.lower().endswith(".docx"):
        import docx

        return {"text": "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)}
    return {"text": data.decode("utf-8", "ignore")}


@app.get("/sources")
def sources(x_token: str = Header("")):
    me(x_token)
    return q("SELECT * FROM sources ORDER BY kind,id")


@app.post("/sources")
def add_source(body: Source, x_token: str = Header("")):
    user = me(x_token)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    if not body.title.strip() or (body.kind != "term" and not body.body.strip()):
        raise HTTPException(400, "Source title and content are required")
    if body.kind == "term" and (not body.banned.strip() or not body.preferred.strip()):
        raise HTTPException(400, "Banned and preferred terms are required")
    source_id = q(
        "INSERT INTO sources(kind,title,body,banned,preferred,created_by) "
        "VALUES(?,?,?,?,?,?)",
        (
            body.kind,
            body.title.strip(),
            (
                body.body.strip()
                or f"Use '{body.preferred.strip()}' instead of '{body.banned.strip()}'."
            ),
            body.banned.strip(),
            body.preferred.strip(),
            user["name"],
        ),
        write=True,
    )
    return {"id": source_id, "ok": True}


@app.get("/submissions")
def list_submissions(x_token: str = Header("")):
    user = me(x_token)
    query = (
        "SELECT id,title,channel,author,status,version FROM submissions "
        "WHERE author=? ORDER BY id DESC"
        if user["role"] == "creator"
        else "SELECT id,title,channel,author,status,version FROM submissions ORDER BY id DESC"
    )
    args = (user["name"],) if user["role"] == "creator" else ()
    return q(query, args)


@app.post("/submissions")
def create_submission(body: NewSub, x_token: str = Header("")):
    user = me(x_token)
    if user["role"] != "creator":
        raise HTTPException(403, "Only creators can submit content")
    if not body.text.strip():
        raise HTTPException(400, "Content is empty")
    created = now()
    submission_id = q(
        "INSERT INTO submissions(title,channel,author,status,text,version,created) "
        "VALUES(?,?,?,?,?,1,?)",
        (body.title.strip() or "Untitled", body.channel, user["name"], "draft", body.text, created),
        write=True,
    )
    q(
        "INSERT INTO versions(submission_id,version,text,note,author,created) "
        "VALUES(?,?,?,?,?,?)",
        (submission_id, 1, body.text, "Initial submission", user["name"], created),
        write=True,
    )
    review = run_review(submission_id)
    return {"id": submission_id, "review": review}


@app.get("/submissions/{submission_id}")
def detail(submission_id: int, x_token: str = Header("")):
    user = me(x_token)
    submission = q(
        "SELECT * FROM submissions WHERE id=?", (submission_id,), one=True
    )
    if not submission:
        raise HTTPException(404, "Not found")
    require_submission_access(submission, user)
    findings = q(
        """SELECT f.*,s.title AS source_title,s.body AS source_body
        FROM findings f LEFT JOIN sources s ON s.id=f.source_id
        WHERE f.submission_id=? AND f.version=? ORDER BY f.s_from""",
        (submission_id, submission["version"]),
    )
    return {
        **submission,
        "findings": findings,
        "comments": q(
            "SELECT * FROM comments WHERE submission_id=? ORDER BY id",
            (submission_id,),
        ),
        "versions": q(
            "SELECT version,note,author,created FROM versions "
            "WHERE submission_id=? ORDER BY version DESC",
            (submission_id,),
        ),
        "activity": q(
            "SELECT status,actor,role,reason,created FROM approval_activity "
            "WHERE submission_id=? ORDER BY id DESC",
            (submission_id,),
        ),
    }


@app.post("/submissions/{submission_id}/rereview")
def rereview(submission_id: int, x_token: str = Header("")):
    user = me(x_token)
    submission = q("SELECT * FROM submissions WHERE id=?", (submission_id,), one=True)
    if not submission:
        raise HTTPException(404, "Not found")
    require_submission_access(submission, user)
    if submission["status"] in ("approved", "rejected"):
        raise HTTPException(409, "A finalized submission cannot be re-reviewed")
    if user["role"] == "creator" and submission["author"] != user["name"]:
        raise HTTPException(403, "You cannot review another creator's submission")
    if user["role"] == "creator" and submission["status"] not in (
        "draft",
        "changes_requested",
    ):
        raise HTTPException(409, "Creators can re-review only editable submissions")
    return {"ok": True, "review": run_review(submission_id)}


@app.put("/submissions/{submission_id}")
def edit_submission(submission_id: int, body: EditSub, x_token: str = Header("")):
    user = me(x_token)
    submission = q("SELECT * FROM submissions WHERE id=?", (submission_id,), one=True)
    if not submission:
        raise HTTPException(404, "Not found")
    require_submission_access(submission, user)
    if user["role"] not in ("creator", "admin") or (
        user["role"] == "creator" and submission["author"] != user["name"]
    ):
        raise HTTPException(403, "Only the submission's creator or an admin can edit it")
    if submission["status"] not in ("draft", "changes_requested"):
        raise HTTPException(409, "Only draft or changes-requested content can be edited")
    if not body.text.strip():
        raise HTTPException(400, "Content is empty")
    version = submission["version"] + 1
    q(
        "UPDATE submissions SET title=?,channel=?,text=?,version=?,status='draft' "
        "WHERE id=?",
        (body.title.strip() or "Untitled", body.channel, body.text, version, submission_id),
        write=True,
    )
    q(
        "INSERT INTO versions(submission_id,version,text,note,author,created) "
        "VALUES(?,?,?,?,?,?)",
        (submission_id, version, body.text, body.note.strip() or "Manual edit", user["name"], now()),
        write=True,
    )
    return {"ok": True, "review": run_review(submission_id)}


@app.post("/findings/{finding_id}/decision")
def decide(finding_id: int, body: Decision, x_token: str = Header("")):
    user = me(x_token)
    finding = q("SELECT * FROM findings WHERE id=?", (finding_id,), one=True)
    if not finding:
        raise HTTPException(404, "Not found")
    submission = q(
        "SELECT * FROM submissions WHERE id=?", (finding["submission_id"],), one=True
    )
    require_submission_access(submission, user)
    if submission["status"] not in ("draft", "changes_requested"):
        raise HTTPException(409, "Findings can be changed only before manager review")
    if user["role"] not in ("creator", "admin") or (
        user["role"] == "creator" and submission["author"] != user["name"]
    ):
        raise HTTPException(403, "Only the submission's creator or an admin can decide findings")
    if finding["version"] != submission["version"] or finding["status"] != "pending":
        raise HTTPException(409, "Finding is no longer pending for the current version")
    if body.decision == "rejected":
        q(
            "UPDATE findings SET status='rejected' WHERE id=?",
            (finding_id,),
            write=True,
        )
        return {"ok": True}
    if not finding["suggestion"]:
        raise HTTPException(
            400, "No suggestion to accept. Edit manually or reject the finding."
        )
    if submission["text"][finding["s_from"] : finding["s_to"]] != finding["snippet"]:
        raise HTTPException(409, "Text changed. Re-run review.")
    updated_text = (
        submission["text"][: finding["s_from"]]
        + finding["suggestion"]
        + submission["text"][finding["s_to"] :]
    )
    version = submission["version"] + 1
    q(
        "UPDATE submissions SET text=?,version=?,status='draft' WHERE id=?",
        (updated_text, version, submission["id"]),
        write=True,
    )
    q(
        "INSERT INTO versions(submission_id,version,text,note,author,created) "
        "VALUES(?,?,?,?,?,?)",
        (
            submission["id"],
            version,
            updated_text,
            f"Accepted {finding['ftype']} suggestion: "
            f"'{finding['snippet'].strip()}' -> '{finding['suggestion'].strip()}'",
            user["name"],
            now(),
        ),
        write=True,
    )
    return {"ok": True, "review": run_review(submission["id"])}


@app.post("/submissions/{submission_id}/comments")
def comment(submission_id: int, body: Comment, x_token: str = Header("")):
    user = me(x_token)
    submission = q("SELECT * FROM submissions WHERE id=?", (submission_id,), one=True)
    if not submission:
        raise HTTPException(404, "Not found")
    require_submission_access(submission, user)
    if not body.body.strip():
        raise HTTPException(400, "Comment cannot be empty")
    q(
        "INSERT INTO comments(submission_id,author,role,body,created) "
        "VALUES(?,?,?,?,?)",
        (submission_id, user["name"], user["role"], body.body.strip(), now()),
        write=True,
    )
    return {"ok": True}


@app.post("/submissions/{submission_id}/status")
def set_status(submission_id: int, body: Status, x_token: str = Header("")):
    user = me(x_token)
    submission = q("SELECT * FROM submissions WHERE id=?", (submission_id,), one=True)
    if not submission:
        raise HTTPException(404, "Not found")
    if submission["status"] in ("approved", "rejected"):
        if body.status == submission["status"]:
            return {"ok": True}
        raise HTTPException(409, "A finalized submission cannot change status")
    if body.status == "in_review":
        if user["role"] not in ("creator", "admin") or (
            user["role"] == "creator" and submission["author"] != user["name"]
        ):
            raise HTTPException(403, "Only the submission's creator or an admin can submit it for review")
        if submission["status"] in ("approved", "rejected"):
            raise HTTPException(409, "A final decision cannot be reopened")
    elif user["role"] not in ("manager", "reviewer", "admin"):
        raise HTTPException(403, "Your role cannot make review decisions")
    elif submission["status"] != "in_review":
        raise HTTPException(409, "Submit the content for manager review first")
    if body.status == "approved":
        pending = q(
            """SELECT count(*) AS n FROM findings f
            JOIN submissions s ON s.id=f.submission_id AND s.version=f.version
            WHERE f.submission_id=? AND f.status='pending' AND f.severity='high'""",
            (submission_id,),
            one=True,
        )["n"]
        if pending and not body.reason.strip():
            raise HTTPException(
                400,
                f"{pending} high-severity finding(s) unresolved. Give a reason to override.",
            )
    reason = body.reason.strip()
    q(
        "UPDATE submissions SET status=? WHERE id=?",
        (body.status, submission_id),
        write=True,
    )
    created = now()
    q(
        "INSERT INTO comments(submission_id,author,role,body,created) "
        "VALUES(?,?,?,?,?)",
        (
            submission_id,
            user["name"],
            user["role"],
            f"Status: {body.status}" + (f". Reason: {reason}" if reason else ""),
            created,
        ),
        write=True,
    )
    q(
        """INSERT INTO approval_activity(
            submission_id,status,actor,role,reason,created
        ) VALUES(?,?,?,?,?,?)""",
        (submission_id, body.status, user["name"], user["role"], reason, created),
        write=True,
    )
    return {"ok": True}


def seed_demo_data():
    init()
    admin = q("SELECT name FROM users WHERE role='admin' ORDER BY id LIMIT 1", one=True)
    owner = admin["name"] if admin else None
    samples = [
        (
            "guideline",
            "Brand Tone Guidelines",
            "Use professional, honest, and clear language. Avoid exaggerated promotional statements, unsupported superlatives, and misleading guarantees.",
            "",
            "",
        ),
        (
            "fact",
            "Approved Product Facts",
            "Our app offers digital services. Pricing and savings vary by plan. We do not guarantee a fixed percentage of savings for every customer.",
            "",
            "",
        ),
        (
            "term",
            "Approved Terminology",
            'Use "affordable plans" instead of "cheap plans". Use "BrandSentinel" as the official product name.',
            "cheap plans",
            "affordable plans",
        ),
    ]
    inserted = []
    for kind, title, body, banned, preferred in samples:
        equivalents = q("SELECT * FROM sources WHERE kind=?", (kind,))
        normalized_body = " ".join(body.casefold().split())
        if any(
            source["title"].casefold() == title.casefold()
            or " ".join((source["body"] or "").casefold().split())
            == normalized_body
            or (
                kind == "term"
                and (source["banned"] or "").casefold() == banned.casefold()
                and (source["preferred"] or "").casefold() == preferred.casefold()
            )
            for source in equivalents
        ):
            continue
        source_id = q(
            "INSERT INTO sources(kind,title,body,banned,preferred,created_by) "
            "VALUES(?,?,?,?,?,?)",
            (kind, title, body, banned, preferred, owner),
            write=True,
        )
        inserted.append(source_id)
    return {"inserted": len(inserted), "source_ids": inserted}


def _cli():
    parser = argparse.ArgumentParser(description="Manage the local BrandSentinel database.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="Create a named login with a fixed role.")
    create.add_argument("--name", required=True)
    create.add_argument("--role", required=True, choices=sorted(ROLES))
    seed = commands.add_parser("seed-demo", help="Add missing sample brand sources.")
    args = parser.parse_args()
    init()
    if args.command == "create-user":
        import getpass

        password = getpass.getpass("Password (at least 12 characters): ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            parser.error("Passwords do not match.")
        try:
            user_id = create_user(args.name, args.role, password)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"Created {args.role} user '{args.name}' (id {user_id}).")
    elif args.command == "seed-demo":
        result = seed_demo_data()
        print(f"Added {result['inserted']} missing demo source(s).")


if __name__ == "__main__":
    _cli()
