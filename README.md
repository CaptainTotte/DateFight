# Date Fight

A small date-polling web app — pick the day that works for everyone. Create an
event with a few candidate dates, share the 8-character code, and let guests vote
on which days they can make it. Results update live with animated bars.

## Stack

- **Backend** — FastAPI + SQLite (raw `sqlite3`, no ORM), served by uvicorn
- **Frontend** — Vanilla HTML/CSS/JS, no framework and no build step
- **Infra** — Docker Compose with two services:
  - `api` — the FastAPI backend
  - `web` — nginx that serves the static frontend and proxies `/api/` to `api`

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

1. Open the admin panel and log in with the admin password.
2. Create an event: give it a title, an optional description, and add as many
   candidate dates as you like (rows are added/removed dynamically).
3. After creation the 8-character code appears in a code box with a copy button —
   share it with your guests.
4. The events list shows each event's code, vote count and dates. Deleting an
   event cascades and removes all of its votes.

### Voting

1. A guest opens the landing page and enters the event code.
2. They see the event title/description and click the dates they can make it
   (multi-select — selected cards get a checkmark and a glow).
3. After entering their name and submitting, the results appear instantly without
   a page reload: an animated bar per date with vote percentages, the leading date
   highlighted in green, and a list of who picked which days.

## API

All admin endpoints require an `Authorization: Bearer <password>` header.

| Method | Endpoint                  | Auth  | Body / notes |
| ------ | ------------------------- | ----- | ------------ |
| POST   | `/auth/verify`            | —     | `{ password }` → `{ valid }` |
| POST   | `/events`                 | admin | `{ title, description, dates[] }` → `{ id, code }` |
| GET    | `/events`                 | admin | list of events with vote counts and dates |
| DELETE | `/events/{id}`            | admin | cascades to votes |
| GET    | `/events/by-code/{code}`  | —     | `{ event, dates, tallies, votes }` |
| POST   | `/votes`                  | —     | `{ event_id, first_name, last_name, date_ids[] }` |

> Endpoints are exposed under `/api/...` from the browser (nginx strips the
> `/api/` prefix before proxying to the backend).

## Data model

- **events** — `id` (uuid), `title`, `description`, `code` (8-char random), `created_at`
- **event_dates** — `id`, `event_id`, `date` (`YYYY-MM-DD`)
- **votes** — `id`, `event_id`, `first_name`, `last_name`, `voted_at`
- **vote_dates** — `vote_id`, `date_id` (many-to-many between votes and dates)

The SQLite database is stored in the `db-data` Docker volume, so it survives
container restarts.

## Project layout

```
docker-compose.yml
nginx.conf
.env.example
backend/
  Dockerfile
  requirements.txt
  main.py            # entire API in one file
frontend/
  index.html         # landing + vote + results (SPA with hash routing)
  pages/admin.html   # admin panel
```

## Local development without Docker

```bash
cd backend
pip install -r requirements.txt
ADMIN_PASSWORD=admin123 DB_PATH=./samdag.db uvicorn main:app --reload
```

Then serve `frontend/` with any static server and point `/api/` at the backend
(the Docker setup does this for you via nginx).
# DateFight
