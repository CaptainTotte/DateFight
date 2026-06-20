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
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

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


@app.on_event("startup")
def startup():
    init_db()


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def require_admin(authorization: str = Header(default="")):
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization[len("Bearer ") :]
    if token != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def gen_code():
    return "".join(random.choices(string.digits, k=4))


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class AuthIn(BaseModel):
    password: str


class EventIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    dates: list[str] = []


class UpdateEventDatesIn(BaseModel):
    dates: list[str] = []

class VoteIn(BaseModel):
    event_id: str
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    date_ids: list[int] = []


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.post("/auth/verify")
def auth_verify(body: AuthIn):
    return {"valid": body.password == ADMIN_PASSWORD}


@app.post("/events")
def create_event(body: EventIn, _: bool = Depends(require_admin)):
    event_id = str(uuid.uuid4())
    with get_db() as conn:
        # Ensure the generated code is unique.
        code = gen_code()
        while conn.execute("SELECT 1 FROM events WHERE code = ?", (code,)).fetchone():
            code = gen_code()

        conn.execute(
            "INSERT INTO events (id, title, description, code, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_id, body.title.strip(), body.description.strip(), code, now_iso()),
        )
        for d in body.dates:
            d = d.strip()
            if d:
                conn.execute(
                    "INSERT INTO event_dates (event_id, date) VALUES (?, ?)",
                    (event_id, d),
                )
    return {"id": event_id, "code": code}


@app.get("/events")
def list_events(_: bool = Depends(require_admin)):
    with get_db() as conn:
        events = conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for e in events:
            dates = conn.execute(
                "SELECT id, date FROM event_dates WHERE event_id = ? ORDER BY date",
                (e["id"],),
            ).fetchall()
            vote_count = conn.execute(
                "SELECT COUNT(*) AS c FROM votes WHERE event_id = ?", (e["id"],)
            ).fetchone()["c"]
            result.append(
                {
                    "id": e["id"],
                    "title": e["title"],
                    "description": e["description"],
                    "code": e["code"],
                    "created_at": e["created_at"],
                    "vote_count": vote_count,
                    "dates": [{"id": d["id"], "date": d["date"]} for d in dates],
                }
            )
    return result


@app.patch("/events/{event_id}")
def update_event_dates(event_id: str, body: UpdateEventDatesIn, _: bool = Depends(require_admin)):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Event not found")
        conn.execute("DELETE FROM event_dates WHERE event_id = ?", (event_id,))
        for d in body.dates:
            d = d.strip()
            if d:
                conn.execute(
                    "INSERT INTO event_dates (event_id, date) VALUES (?, ?)", (event_id, d)
                )
    return {"updated": True}


@app.delete("/events/{event_id}")
def delete_event(event_id: str, _: bool = Depends(require_admin)):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Event not found")
    return {"deleted": True}


@app.get("/events/by-code/{code}")
def event_by_code(code: str):
    with get_db() as conn:
        e = conn.execute(
            "SELECT * FROM events WHERE code = ?", (code.strip().upper(),)
        ).fetchone()
        if not e:
            raise HTTPException(status_code=404, detail="Event not found")

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

    return {
        "event": {
            "id": e["id"],
            "title": e["title"],
            "description": e["description"],
            "code": e["code"],
        },
        "dates": [{"id": d["id"], "date": d["date"]} for d in dates],
        "tallies": tallies,
        "votes": vote_list,
    }


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
