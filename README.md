# DateFight

Date-polling web app — anyone can create an event with candidate dates, share a 4-digit code, and let guests vote on which days work. Results update live with animated bars. No login, no admin password: the event creator gets a private admin code to edit their own event.

## Stack

- **Backend** — FastAPI + SQLite (raw `sqlite3`, no ORM), served by uvicorn
- **Frontend** — Vanilla HTML/CSS/JS, no framework, no build step
- **Infra** — Docker Compose with two services:
  - `api` — FastAPI backend
  - `web` — nginx serving static files and proxying `/api/` to the backend

## Quick start

```bash
docker compose up -d
# → http://localhost:3000
```

No configuration needed — there is no global admin password.

## How it works

Everything lives on the root page (`index.html`); there is no separate admin page.

### Create an event

1. On the landing page, click **"Skapa nytt event"**.
2. Enter a title, optional description, and pick candidate dates with the drag-to-select calendar.
3. You get two codes:
   - **Röstkod** — a 4-digit numeric code to share with guests (voting).
   - **Admin-kod** — a 4-char alphanumeric code (always contains a letter). Save it — it's the only way to edit or delete the event later.

### One code form, two outcomes

The landing page has a single code input. The backend resolves the entered code:

- A numeric **voting code** → opens the vote + results view.
- An alphanumeric **admin code** → opens the manage view (edit title/description/dates, share the voting code, see results, delete the event).

### Voting

1. Enter the voting code. A single-month calendar shows event dates in green — click/tap to pick the days that work; browse months with ‹ ›.
2. Enter your name and submit. Results appear instantly: animated bars per date (leading date in green), top 5 shown with the rest behind a toggle, plus who picked which days. Dates with 0 votes are hidden.
3. Duplicate votes are blocked by localStorage (client) and by name deduplication (server — same first + last name per event returns 409).

## API

Edit/delete require `Authorization: Bearer <admin_code>` for that specific event.

| Method  | Endpoint                  | Auth        | Body / notes |
| ------- | ------------------------- | ----------- | ------------ |
| POST    | `/events`                 | —           | `{ title, description, dates[] }` → `{ id, code, admin_code }` |
| GET     | `/events/resolve/{code}`  | —           | `{ mode: "vote"\|"admin", event, dates, tallies, votes }` (admin_code only in admin mode) |
| GET     | `/events/by-code/{code}`  | —           | `{ event, dates, tallies, votes }` (voting code) |
| PATCH   | `/events/{id}`            | admin_code  | `{ title?, description?, dates? }` — updates provided fields; `dates` replaces |
| DELETE  | `/events/{id}`            | admin_code  | cascades to votes |
| POST    | `/votes`                  | —           | `{ event_id, first_name, last_name, date_ids[] }` |

Endpoints are exposed under `/api/...` from the browser (nginx strips the prefix before proxying).

## Data model

- **events** — `id` (uuid), `title`, `description`, `code` (4-digit numeric), `admin_code` (4-char alphanumeric), `created_at`
- **event_dates** — `id`, `event_id`, `date` (`YYYY-MM-DD`)
- **votes** — `id`, `event_id`, `first_name`, `last_name`, `voted_at`
- **vote_dates** — `vote_id`, `date_id` (many-to-many)

SQLite database lives in the `db-data` Docker volume and survives restarts.

## Project layout

```
docker-compose.yml
nginx.conf
.env.example
backend/
  Dockerfile
  requirements.txt
  main.py              # entire API in one file
frontend/
  index.html           # landing + create + vote + manage (SPA, hash routing)
  img/                 # logo assets
```

## Local development without Docker

```bash
cd backend
pip install -r requirements.txt
DB_PATH=./datefight.db uvicorn main:app --reload
```

Then serve `frontend/` with any static file server and point `/api/` at the backend (the Docker setup handles this via nginx).
