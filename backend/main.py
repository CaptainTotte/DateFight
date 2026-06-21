import os
import sqlite3
import uuid
import random
import string
from datetime import datetime, timezone
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("DB_PATH", "/data/samdag.db")

app = FastAPI(title="DateFight API")

# Permissive CORS so the API can be hit directly during local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                code        TEXT NOT NULL UNIQUE,
                admin_code  TEXT UNIQUE,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_dates (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                date     TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS votes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id   TEXT NOT NULL,
                first_name TEXT NOT NULL,
                last_name  TEXT NOT NULL,
                voted_at   TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS vote_dates (
                vote_id INTEGER NOT NULL,
                date_id INTEGER NOT NULL,
                PRIMARY KEY (vote_id, date_id),
                FOREIGN KEY (vote_id) REFERENCES votes(id) ON DELETE CASCADE,
                FOREIGN KEY (date_id) REFERENCES event_dates(id) ON DELETE CASCADE
            );
            """
        )

        # Migration: add admin_code to pre-existing events tables and backfill.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        if "admin_code" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN admin_code TEXT")
        for e in conn.execute("SELECT id FROM events WHERE admin_code IS NULL").fetchall():
            conn.execute(
                "UPDATE events SET admin_code = ? WHERE id = ?",
                (_unique_admin_code(conn), e["id"]),
            )


@app.on_event("startup")
def startup():
    init_db()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def now_iso():
    return datetime.now(timezone.utc).isoformat()


def gen_code():
    """4-digit numeric voting code."""
    return "".join(random.choices(string.digits, k=4))


def gen_admin_code():
    """4-char alphanumeric admin code, guaranteed to contain at least one
    letter so it can never collide with a purely numeric voting code."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(alphabet, k=4))
        if any(c in string.ascii_uppercase for c in code):
            return code


def _unique_admin_code(conn):
    code = gen_admin_code()
    while conn.execute("SELECT 1 FROM events WHERE admin_code = ?", (code,)).fetchone():
        code = gen_admin_code()
    return code


def require_event_admin(event_id: str, authorization: str = Header(default="")):
    """Authorize edits/deletes against the event's own admin_code."""
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization[len("Bearer ") :]
    token = token.strip().upper()
    with get_db() as conn:
        e = conn.execute(
            "SELECT admin_code FROM events WHERE id = ?", (event_id,)
        ).fetchone()
    if not e:
        raise HTTPException(status_code=404, detail="Event not found")
    if not token or token != (e["admin_code"] or ""):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def build_event_payload(conn, e, include_admin=False):
    """Assemble the dates/tallies/votes payload for an event row."""
    dates = conn.execute(
        "SELECT id, date FROM event_dates WHERE event_id = ? ORDER BY date",
        (e["id"],),
    ).fetchall()
    votes = conn.execute(
        "SELECT id, first_name, last_name, voted_at FROM votes "
        "WHERE event_id = ? ORDER BY voted_at",
        (e["id"],),
    ).fetchall()

    tallies = {d["id"]: 0 for d in dates}
    vote_list = []
    for v in votes:
        picked = conn.execute(
            "SELECT date_id FROM vote_dates WHERE vote_id = ?", (v["id"],)
        ).fetchall()
        picked_ids = [p["date_id"] for p in picked]
        for did in picked_ids:
            if did in tallies:
                tallies[did] += 1
        vote_list.append(
            {
                "first_name": v["first_name"],
                "last_name": v["last_name"],
                "date_ids": picked_ids,
            }
        )

    event = {
        "id": e["id"],
        "title": e["title"],
        "description": e["description"],
        "code": e["code"],
    }
    if include_admin:
        event["admin_code"] = e["admin_code"]

    return {
        "event": event,
        "dates": [{"id": d["id"], "date": d["date"]} for d in dates],
        "tallies": tallies,
        "votes": vote_list,
    }


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class EventIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    dates: list[str] = []


class UpdateEventIn(BaseModel):
    title: str | None = None
    description: str | None = None
    dates: list[str] | None = None

class VoteIn(BaseModel):
    event_id: str
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    date_ids: list[int] = []


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.post("/events")
def create_event(body: EventIn):
    """Public — anyone can create an event."""
    event_id = str(uuid.uuid4())
    with get_db() as conn:
        # Ensure the generated voting code is unique.
        code = gen_code()
        while conn.execute("SELECT 1 FROM events WHERE code = ?", (code,)).fetchone():
            code = gen_code()
        admin_code = _unique_admin_code(conn)

        conn.execute(
            "INSERT INTO events (id, title, description, code, admin_code, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event_id,
                body.title.strip(),
                body.description.strip(),
                code,
                admin_code,
                now_iso(),
            ),
        )
        for d in body.dates:
            d = d.strip()
            if d:
                conn.execute(
                    "INSERT INTO event_dates (event_id, date) VALUES (?, ?)",
                    (event_id, d),
                )
    return {"id": event_id, "code": code, "admin_code": admin_code}


@app.patch("/events/{event_id}")
def update_event(event_id: str, body: UpdateEventIn, _: bool = Depends(require_event_admin)):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Event not found")

        if body.title is not None:
            title = body.title.strip()
            if not title:
                raise HTTPException(status_code=422, detail="Title cannot be empty")
            conn.execute("UPDATE events SET title = ? WHERE id = ?", (title, event_id))
        if body.description is not None:
            conn.execute(
                "UPDATE events SET description = ? WHERE id = ?",
                (body.description.strip(), event_id),
            )
        if body.dates is not None:
            conn.execute("DELETE FROM event_dates WHERE event_id = ?", (event_id,))
            for d in body.dates:
                d = d.strip()
                if d:
                    conn.execute(
                        "INSERT INTO event_dates (event_id, date) VALUES (?, ?)",
                        (event_id, d),
                    )
    return {"updated": True}


@app.delete("/events/{event_id}")
def delete_event(event_id: str, _: bool = Depends(require_event_admin)):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Event not found")
    return {"deleted": True}


@app.get("/events/by-code/{code}")
def event_by_code(code: str):
    """Public voting lookup by numeric voting code."""
    with get_db() as conn:
        e = conn.execute(
            "SELECT * FROM events WHERE code = ?", (code.strip().upper(),)
        ).fetchone()
        if not e:
            raise HTTPException(status_code=404, detail="Event not found")
        return build_event_payload(conn, e, include_admin=False)


@app.get("/events/resolve/{code}")
def resolve_code(code: str):
    """Resolve any code: numeric voting code -> vote mode, alphanumeric
    admin code -> admin mode (includes admin_code)."""
    code = code.strip().upper()
    with get_db() as conn:
        e = conn.execute("SELECT * FROM events WHERE code = ?", (code,)).fetchone()
        if e:
            payload = build_event_payload(conn, e, include_admin=False)
            payload["mode"] = "vote"
            return payload

        e = conn.execute("SELECT * FROM events WHERE admin_code = ?", (code,)).fetchone()
        if e:
            payload = build_event_payload(conn, e, include_admin=True)
            payload["mode"] = "admin"
            return payload

    raise HTTPException(status_code=404, detail="Event not found")


@app.post("/votes")
def create_vote(body: VoteIn):
    with get_db() as conn:
        e = conn.execute(
            "SELECT id FROM events WHERE id = ?", (body.event_id,)
        ).fetchone()
        if not e:
            raise HTTPException(status_code=404, detail="Event not found")

        duplicate = conn.execute(
            "SELECT 1 FROM votes WHERE event_id = ? AND first_name = ? AND last_name = ?",
            (body.event_id, body.first_name.strip(), body.last_name.strip()),
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="Already voted")

        valid_ids = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM event_dates WHERE event_id = ?", (body.event_id,)
            ).fetchall()
        }

        cur = conn.execute(
            "INSERT INTO votes (event_id, first_name, last_name, voted_at) "
            "VALUES (?, ?, ?, ?)",
            (
                body.event_id,
                body.first_name.strip(),
                body.last_name.strip(),
                now_iso(),
            ),
        )
        vote_id = cur.lastrowid
        for did in body.date_ids:
            if did in valid_ids:
                conn.execute(
                    "INSERT INTO vote_dates (vote_id, date_id) VALUES (?, ?)",
                    (vote_id, did),
                )
    return {"id": vote_id}


@app.get("/health")
def health():
    return {"status": "ok"}
