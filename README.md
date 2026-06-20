# DateFight

Date-polling web app — create an event with candidate dates, share a 4-digit code, and let guests vote on which days work. Results update live with animated bars.

## Stack

- **Backend** — FastAPI + SQLite (raw `sqlite3`, no ORM), served by uvicorn
- **Frontend** — Vanilla HTML/CSS/JS, no framework, no build step
- **Infra** — Docker Compose with two services:
  - `api` — FastAPI backend
  - `web` — nginx serving static files and proxying `/api/` to the backend

## Quick start

```bash
cp .env.example .env   # set ADMIN_PASSWORD
docker compose up -d
# → http://localhost:3000
```

- **Vote page:** http://localhost:3000
- **Admin panel:** http://localhost:3000/pages/admin.html

The admin password defaults to `admin123` (override with `ADMIN_PASSWORD` in `.env`).

## How it works

### Admin

1. Log in with the admin password.
2. Create an event: title, optional description, and pick candidate dates using the drag-to-select calendar.
3. A 4-digit numeric code is generated — copy and share it with guests.
4. The event list shows code, vote count and date chips. Each event can be **edited** (change dates) or **deleted** (cascades to all votes).

### Voting

1. Guest opens the landing page and enters the 4-digit code.
2. A single-month calendar is shown with event dates highlighted in green — click or tap to select the days that work. Browse months with ‹ ›.
3. Enter name and submit. Results appear instantly below: animated bars per date (leading date in green), plus a list of who picked which days. Dates with 0 votes are hidden.
4. Duplicate votes are blocked by localStorage (client) and by name deduplication (server — same first + last name per event returns 409).

## API

All admin endpoints require `Authorization: Bearer <password>`.

| Method  | Endpoint                 | Auth  | Body / notes |
| ------- | ------------------------ | ----- | ------------ |
| POST    | `/auth/verify`           | —     | `{ password }` → `{ valid }` |
| POST    | `/events`                | admin | `{ title, description, dates[] }` → `{ id, code }` |
| GET     | `/events`                | admin | list with vote counts and dates |
| PATCH   | `/events/{id}`           | admin | `{ dates[] }` — replace event dates |
| DELETE  | `/events/{id}`           | admin | cascades to votes |
| GET     | `/events/by-code/{code}` | —     | `{ event, dates, tallies, votes }` |
| POST    | `/votes`                 | —     | `{ event_id, first_name, last_name, date_ids[] }` |

Endpoints are exposed under `/api/...` from the browser (nginx strips the prefix before proxying).

## Data model

- **events** — `id` (uuid), `title`, `description`, `code` (4-digit numeric), `created_at`
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
  index.html           # landing + vote + results (SPA, hash routing)
  pages/admin.html     # admin panel
  img/                 # logo assets
```

## Local development without Docker

```bash
cd backend
pip install -r requirements.txt
ADMIN_PASSWORD=admin123 DB_PATH=./datefight.db uvicorn main:app --reload
```

Then serve `frontend/` with any static file server and point `/api/` at the backend (the Docker setup handles this via nginx).
