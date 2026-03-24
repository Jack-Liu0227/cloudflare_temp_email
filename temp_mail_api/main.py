from __future__ import annotations

import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

BASE_URL = os.getenv("TEMP_MAIL_BASE_URL", "https://mail.2802644093.com").rstrip("/")
DEFAULT_DOMAIN = os.getenv("TEMP_MAIL_DEFAULT_DOMAIN", "2802644093.com")
CUSTOM_AUTH = os.getenv("TEMP_MAIL_CUSTOM_AUTH", "")
DEFAULT_LANG = os.getenv("TEMP_MAIL_LANG", "zh")
DB_PATH = Path(os.getenv("TEMP_MAIL_DB_PATH", "./data/inboxes.db"))
DEFAULT_CODE_REGEX = r"\b\d{4,8}\b"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL UNIQUE,
                jwt TEXT NOT NULL,
                requested_name TEXT,
                domain TEXT NOT NULL,
                latest_mail_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class CreateInboxesRequest(BaseModel):
    name: str | None = Field(default=None, description="Base name for one inbox or prefix for multiple inboxes")
    domain: str = Field(default=DEFAULT_DOMAIN)
    count: int = Field(default=1, ge=1, le=100)
    start_index: int = Field(default=1, ge=1)
    auto_name_when_empty: bool = True
    cf_token: str | None = None


class InboxRecord(BaseModel):
    id: int
    address: str
    jwt: str
    requested_name: str | None = None
    domain: str
    latest_mail_id: str | None = None
    created_at: str
    updated_at: str


class VerificationCodeResult(BaseModel):
    inbox_id: int
    address: str
    matched: bool
    code: str | None = None
    mail_id: str | None = None
    subject: str | None = None
    from_address: str | None = None
    checked_count: int = 0


class PollCodeRequest(BaseModel):
    regex: str = DEFAULT_CODE_REGEX
    timeout_seconds: int = Field(default=120, ge=1, le=1800)
    poll_interval_seconds: int = Field(default=5, ge=1, le=60)
    sender_contains: str | None = None
    subject_contains: str | None = None
    only_unseen: bool = False


def row_to_inbox(row: sqlite3.Row) -> InboxRecord:
    return InboxRecord(
        id=row["id"],
        address=row["address"],
        jwt=row["jwt"],
        requested_name=row["requested_name"],
        domain=row["domain"],
        latest_mail_id=row["latest_mail_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def client_headers(jwt: str | None = None) -> dict[str, str]:
    headers = {"x-lang": DEFAULT_LANG}
    if CUSTOM_AUTH:
        headers["x-custom-auth"] = CUSTOM_AUTH
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    return headers


async def create_remote_inbox(name: str | None, domain: str, cf_token: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"domain": domain}
    if name is not None:
        payload["name"] = name
    if cf_token:
        payload["cf_token"] = cf_token
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{BASE_URL}/api/new_address", json=payload, headers=client_headers())
    if response.status_code >= 300:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


async def fetch_remote_mails(jwt: str, limit: int, offset: int) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{BASE_URL}/api/mails",
            params={"limit": limit, "offset": offset},
            headers=client_headers(jwt),
        )
    if response.status_code >= 300:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


async def fetch_remote_mail(jwt: str, mail_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{BASE_URL}/api/mail/{mail_id}", headers=client_headers(jwt))
    if response.status_code >= 300:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


def extract_code_from_mail(mail: dict[str, Any], regex: str, sender_contains: str | None, subject_contains: str | None) -> str | None:
    sender_text = " ".join(
        str(mail.get(key, ""))
        for key in ("from", "from_name", "from_mail", "sender", "reply_to")
        if mail.get(key)
    )
    subject_text = str(mail.get("subject", ""))
    if sender_contains and sender_contains.lower() not in sender_text.lower():
        return None
    if subject_contains and subject_contains.lower() not in subject_text.lower():
        return None

    searchable_text = "\n".join(str(value) for value in mail.values() if isinstance(value, str))
    match = re.search(regex, searchable_text)
    return match.group(0) if match else None


def get_inbox_or_404(inbox_id: int) -> InboxRecord:
    with closing(db_connect()) as conn:
        row = conn.execute("SELECT * FROM inboxes WHERE id = ?", (inbox_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Inbox not found")
    return row_to_inbox(row)


def update_latest_mail(inbox_id: int, latest_mail_id: str | None) -> None:
    with closing(db_connect()) as conn:
        conn.execute(
            "UPDATE inboxes SET latest_mail_id = ?, updated_at = ? WHERE id = ?",
            (latest_mail_id, utc_now(), inbox_id),
        )
        conn.commit()


app = FastAPI(title="Temp Mail Automation API", version="1.0.0")


@app.on_event("startup")
def startup() -> None:
    ensure_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "base_url": BASE_URL, "default_domain": DEFAULT_DOMAIN}


@app.post("/api/inboxes", response_model=list[InboxRecord])
async def create_inboxes(payload: CreateInboxesRequest) -> list[InboxRecord]:
    created: list[InboxRecord] = []
    for index in range(payload.count):
        if payload.count == 1:
            requested_name = payload.name
        elif payload.name:
            requested_name = f"{payload.name}{payload.start_index + index:03d}"
        else:
            requested_name = None if payload.auto_name_when_empty else str(payload.start_index + index)

        remote = await create_remote_inbox(requested_name, payload.domain, payload.cf_token)
        now = utc_now()
        with closing(db_connect()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO inboxes(address, jwt, requested_name, domain, latest_mail_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (remote["address"], remote["jwt"], requested_name, payload.domain, None, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM inboxes WHERE id = ?", (cursor.lastrowid,)).fetchone()
        created.append(row_to_inbox(row))
    return created


@app.get("/api/inboxes", response_model=list[InboxRecord])
def list_inboxes() -> list[InboxRecord]:
    with closing(db_connect()) as conn:
        rows = conn.execute("SELECT * FROM inboxes ORDER BY id DESC").fetchall()
    return [row_to_inbox(row) for row in rows]


@app.get("/api/inboxes/{inbox_id}", response_model=InboxRecord)
def get_inbox(inbox_id: int) -> InboxRecord:
    return get_inbox_or_404(inbox_id)


@app.get("/api/inboxes/{inbox_id}/mails")
async def get_mails(inbox_id: int, limit: int = Query(default=20, ge=1, le=200), offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
    inbox = get_inbox_or_404(inbox_id)
    result = await fetch_remote_mails(inbox.jwt, limit, offset)
    mails = result.get("results") or []
    if mails:
        update_latest_mail(inbox_id, str(mails[0].get("id")))
    return result


@app.get("/api/inboxes/{inbox_id}/mails/{mail_id}")
async def get_mail(inbox_id: int, mail_id: str) -> dict[str, Any]:
    inbox = get_inbox_or_404(inbox_id)
    return await fetch_remote_mail(inbox.jwt, mail_id)


@app.get("/api/inboxes/{inbox_id}/verification-code", response_model=VerificationCodeResult)
async def get_verification_code(
    inbox_id: int,
    regex: str = DEFAULT_CODE_REGEX,
    sender_contains: str | None = None,
    subject_contains: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> VerificationCodeResult:
    inbox = get_inbox_or_404(inbox_id)
    result = await fetch_remote_mails(inbox.jwt, limit, 0)
    mails = result.get("results") or []
    checked = 0
    for mail in mails:
        checked += 1
        mail_id = str(mail.get("id"))
        full_mail = await fetch_remote_mail(inbox.jwt, mail_id)
        code = extract_code_from_mail(full_mail, regex, sender_contains, subject_contains)
        if code:
            update_latest_mail(inbox_id, mail_id)
            return VerificationCodeResult(
                inbox_id=inbox.id,
                address=inbox.address,
                matched=True,
                code=code,
                mail_id=mail_id,
                subject=full_mail.get("subject"),
                from_address=full_mail.get("from_mail") or full_mail.get("from"),
                checked_count=checked,
            )
    return VerificationCodeResult(inbox_id=inbox.id, address=inbox.address, matched=False, checked_count=checked)


@app.post("/api/inboxes/{inbox_id}/poll-verification-code", response_model=VerificationCodeResult)
async def poll_verification_code(inbox_id: int, payload: PollCodeRequest) -> VerificationCodeResult:
    inbox = get_inbox_or_404(inbox_id)
    deadline = time.monotonic() + payload.timeout_seconds
    seen_threshold = inbox.latest_mail_id if payload.only_unseen else None

    while time.monotonic() < deadline:
        result = await fetch_remote_mails(inbox.jwt, 20, 0)
        mails = result.get("results") or []
        checked = 0
        for mail in mails:
            checked += 1
            mail_id = str(mail.get("id"))
            if seen_threshold and mail_id == seen_threshold:
                break
            full_mail = await fetch_remote_mail(inbox.jwt, mail_id)
            code = extract_code_from_mail(full_mail, payload.regex, payload.sender_contains, payload.subject_contains)
            if code:
                update_latest_mail(inbox_id, mail_id)
                return VerificationCodeResult(
                    inbox_id=inbox.id,
                    address=inbox.address,
                    matched=True,
                    code=code,
                    mail_id=mail_id,
                    subject=full_mail.get("subject"),
                    from_address=full_mail.get("from_mail") or full_mail.get("from"),
                    checked_count=checked,
                )
        time.sleep(payload.poll_interval_seconds)

    return VerificationCodeResult(inbox_id=inbox.id, address=inbox.address, matched=False)
