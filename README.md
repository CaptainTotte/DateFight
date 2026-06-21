# DateFight

A lightweight date-polling web app. Create an event with candidate dates, share a 4-digit code with your guests, and let everyone vote on which days work. Results update live with animated bars showing the leading date in green.

No accounts, no login required. Each event has its own private admin code — only the creator can edit or delete it.

## Stack

- **Backend** — FastAPI + SQLite (`sqlite3`, no ORM), served by uvicorn
- **Frontend** — Vanilla HTML/CSS/JS, no framework, no build step
- **Infra** — Docker Compose: `api` (FastAPI) + `web` (nginx static files + `/api/` proxy)

## Quick start

```bash
docker compose up -d
# → http://localhost:3000
```

No configuration needed out of the box.

### Demo mode

Set `DEMO=true` in your `.env` to auto-create a demo event on startup:

```
DEMO=true
```

Then log in with:
- Voting code: `0000`
- Admin code: `DEMO`

See [`.env.example`](.env.example) for reference.

## How it works

Everything lives on a single page (`index.html`). There is no separate admin panel.

### Create an event

1. Click **+ Create new event** on the landing page.
2. Enter a title, optional description, and pick candidate dates from the calendar.
3. You receive two codes:
   - **Voting code** — a 4-digit numeric code to share with guests.
   - **Admin code** — a 4-character alphanumeric code (always contains a letter). Keep this private — it's the only way to edit or delete the event later.

### One input, two outcomes

The landing page has a single code field. The backend resolves what was entered:

- A numeric **voting code** → opens the vote and results view.
- An alphanumeric **admin code** → opens the manage view (edit title, description, dates; share the voting code; see results; delete the event).

### Voting

1. Enter the voting code. The calendar shows the event's candidate dates — tap to select the days that work for you.
2. Enter your name and submit. Results appear immediately: bars per date (leading date highlighted in green), top 5 shown with the rest behind a toggle, plus a breakdown of who can make each day.
3. Duplicate votes are blocked by name deduplication server-side (same first + last name per event returns 409) and flagged client-side via localStorage.

## API

Edit and delete endpoints require `Authorization: Bearer <admin_code>` for that specific event.

| Method | Endpoint | Auth | Notes |
|--------|----------|------|-------|
| `POST` | `/events` | — | `{ title, description, dates[] }` → `{ id, code, admin_code }` |
| `GET` | `/events/resolve/{code}` | — | Returns `{ mode: "vote"\|"admin", event, dates, tallies, votes }`. `admin_code` is only included in admin mode. |
| `GET` | `/events/by-code/{code}` | — | Voting code lookup |
| `PATCH` | `/events/{id}` | admin_code | `{ title?, description?, dates? }` — updates provided fields; `dates` replaces all existing dates |
| `DELETE` | `/events/{id}` | admin_code | Cascades to votes |
| `POST` | `/votes` | — | `{ event_id, first_name, last_name, date_ids[] }` |

All endpoints are available at `/api/...` from the browser (nginx strips the prefix before proxying).

## Data model

| Table | Columns |
|-------|---------|
| `events` | `id` (UUID), `title`, `description`, `code` (4-digit numeric), `admin_code` (4-char alphanumeric), `created_at` |
| `event_dates` | `id`, `event_id`, `date` (YYYY-MM-DD) |
| `votes` | `id`, `event_id`, `first_name`, `last_name`, `voted_at` |
| `vote_dates` | `vote_id`, `date_id` (many-to-many join) |

The SQLite database lives in the `db-data` Docker volume and persists across restarts.

## Project layout

```
docker-compose.yml
nginx.conf
.env.example
backend/
  Dockerfile
  requirements.txt
  main.py          # entire API in one file
frontend/
  index.html       # SPA — landing, create, vote, manage views
  img/             # logo assets
```

## Local development without Docker

```bash
cd backend
pip install -r requirements.txt
DB_PATH=./datefight.db uvicorn main:app --reload
```

Serve `frontend/` with any static file server and proxy `/api/` to the backend (the Docker setup does this via nginx).
