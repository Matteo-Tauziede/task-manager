# Task Manager API

Flask + JWT task manager: accounts, task CRUD, deadlines, priorities, filtering,
search, and an admin role. Ships with a small web board so you can use the API
without a REST client.

## Run it

```bash
cd task_manager
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export SECRET_KEY="change-me"                          # optional
export JWT_SECRET_KEY="change-me-too"                  # optional

flask --app app seed        # optional demo data: admin/adminpass123, alex/alexpass123
python app.py               # http://127.0.0.1:5000
```

SQLite (`tasks.db`) is created on first start. Point `DATABASE_URL` at Postgres
for anything real.

## Roles

- The **first account created on an empty database becomes the admin**; every
  account after that is a regular user.
- Regular users only ever see and touch their own tasks.
- Admins can read/edit/delete any task, list `?scope=all`, list users, promote or
  demote them, and delete accounts (which cascades to their tasks).

## Endpoints

| Method | Path | Who |
| --- | --- | --- |
| POST | `/api/auth/register` | anyone |
| POST | `/api/auth/login` | anyone |
| POST | `/api/auth/refresh` | refresh token |
| GET | `/api/auth/me` | signed in |
| GET | `/api/tasks` | signed in |
| POST | `/api/tasks` | signed in |
| GET | `/api/tasks/<id>` | owner or admin |
| PATCH / PUT | `/api/tasks/<id>` | owner or admin |
| DELETE | `/api/tasks/<id>` | owner or admin |
| GET | `/api/tasks/stats` | signed in |
| GET | `/api/users` | admin |
| PATCH | `/api/users/<id>/role` | admin |
| DELETE | `/api/users/<id>` | admin |

### Query parameters on `GET /api/tasks`

| Parameter | Example | Notes |
| --- | --- | --- |
| `q` | `q=invoice` | searches title and notes |
| `priority` | `priority=high,urgent` | comma separated |
| `status` | `status=todo,in_progress` | comma separated |
| `due_before` / `due_after` | `due_before=2026-08-12T23:59:59Z` | ISO 8601 |
| `overdue` | `overdue=true` | past deadline and not done |
| `has_deadline` | `has_deadline=true` | |
| `sort` | `sort=priority` | `deadline`, `priority`, `created_at`, `updated_at`, `title` |
| `order` | `order=desc` | default `asc` |
| `page`, `per_page` | `page=2&per_page=50` | `per_page` caps at 100 |
| `scope`, `user_id` | `scope=all&user_id=3` | admin only |

Priority sorting is by urgency (`urgent → high → medium → low`), not alphabetical.

## Fields

- `priority`: `low` · `medium` · `high` · `urgent`
- `status`: `todo` · `in_progress` · `done`
- `deadline`: ISO 8601, stored in UTC, returned with a `Z` suffix

## Try it with curl

```bash
# 1. sign up (first account = admin)
curl -s -X POST localhost:5000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"sam","email":"sam@example.com","password":"hunter2hunter2"}'

TOKEN=$(curl -s -X POST localhost:5000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"sam","password":"hunter2hunter2"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. create a task
curl -s -X POST localhost:5000/api/tasks \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"Ship the invoice export","priority":"urgent","deadline":"2026-08-12T17:00:00Z"}'

# 3. filter and search
curl -s -H "Authorization: Bearer $TOKEN" \
  'localhost:5000/api/tasks?priority=urgent,high&sort=deadline&q=invoice'

# 4. update and delete
curl -s -X PATCH localhost:5000/api/tasks/1 \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"status":"done"}'
curl -s -X DELETE localhost:5000/api/tasks/1 -H "Authorization: Bearer $TOKEN"
```

## Before deploying

- Set real `SECRET_KEY` / `JWT_SECRET_KEY` values from the environment.
- The web board keeps tokens in `localStorage`, which is convenient for a demo;
  httpOnly cookies (`JWT_TOKEN_LOCATION = ["cookies"]` plus CSRF protection) are
  the safer choice in production.
- Add a token denylist if you need real sign-out/revocation.
- Run behind a WSGI server (`gunicorn "app:app"`), not `app.run(debug=True)`.
