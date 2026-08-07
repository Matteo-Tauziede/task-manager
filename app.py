"""Task Manager API — Flask + JWT.

Run:
    pip install -r requirements.txt
    python app.py            # http://127.0.0.1:5000

API surface
-----------
POST   /api/auth/register        create an account
POST   /api/auth/login           -> access_token (+ refresh_token)
POST   /api/auth/refresh         swap a refresh token for a fresh access token
GET    /api/auth/me              current user

GET    /api/tasks                list + filter + search + sort + paginate
POST   /api/tasks                create
GET    /api/tasks/<id>           read one
PATCH  /api/tasks/<id>           partial update  (PUT also accepted)
DELETE /api/tasks/<id>           delete
GET    /api/tasks/stats          counts by status / priority / overdue

GET    /api/users                admin only
PATCH  /api/users/<id>/role      admin only
DELETE /api/users/<id>           admin only
"""

import os
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, jsonify, render_template, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    current_user,
    get_jwt_identity,
    jwt_required,
)
from sqlalchemy import or_

from extensions import db, jwt
from models import PRIORITIES, ROLES, STATUSES, Task, User, utcnow


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        JWT_SECRET_KEY=os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-change-me"),
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=2),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=14),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///tasks.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JSON_SORT_KEYS=False,
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    jwt.init_app(app)

    register_jwt_callbacks()
    register_error_handlers(app)
    register_routes(app)
    register_cli(app)

    with app.app_context():
        db.create_all()

    return app


# --------------------------------------------------------------------------
# JWT plumbing
# --------------------------------------------------------------------------
def register_jwt_callbacks():
    @jwt.user_identity_loader
    def user_identity(user):
        # `sub` must be a string in flask-jwt-extended 4.x
        return str(user.id if isinstance(user, User) else user)

    @jwt.user_lookup_loader
    def load_user(_jwt_header, jwt_data):
        return db.session.get(User, int(jwt_data["sub"]))

    @jwt.additional_claims_loader
    def add_claims(user):
        return {"role": user.role} if isinstance(user, User) else {}

    @jwt.expired_token_loader
    def expired(_h, _p):
        return jsonify(error="token_expired", message="Your session expired. Sign in again."), 401

    @jwt.invalid_token_loader
    def invalid(reason):
        return jsonify(error="invalid_token", message=str(reason)), 401

    @jwt.unauthorized_loader
    def missing(reason):
        return jsonify(error="authorization_required", message=str(reason)), 401


def admin_required(fn):
    """Allow the route only for users whose role is `admin`."""

    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if not current_user or not current_user.is_admin:
            return jsonify(error="forbidden", message="Admin access only."), 403
        return fn(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, message, status=400, field=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.field = field


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send a JSON object in the request body.")
    return data


def parse_datetime(value, field="deadline"):
    """Accept ISO 8601, with or without a trailing Z, with or without seconds."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise ApiError(
                f"Use an ISO 8601 date for {field}, e.g. 2026-08-12T17:00:00Z.", field=field
            )
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def check_choice(value, allowed, field):
    if value not in allowed:
        raise ApiError(f"{field} must be one of: {', '.join(allowed)}.", field=field)
    return value


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        payload = {"error": "validation_error", "message": err.message}
        if err.field:
            payload["field"] = err.field
        return jsonify(payload), err.status

    @app.errorhandler(404)
    def handle_404(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="not_found", message="No route matches that URL."), 404
        return render_template("index.html"), 404

    @app.errorhandler(405)
    def handle_405(_e):
        return jsonify(error="method_not_allowed", message="That method is not allowed here."), 405

    @app.errorhandler(500)
    def handle_500(_e):
        db.session.rollback()
        return jsonify(error="server_error", message="Something broke on our side."), 500


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
def register_routes(app):
    # ---- pages ----------------------------------------------------------
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/tasks/<int:task_id>/edit")
    def update_page(task_id):
        return render_template("update.html", task_id=task_id)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", time=utcnow().isoformat() + "Z")

    # ---- auth -----------------------------------------------------------
    @app.post("/api/auth/register")
    def register():
        data = body()
        username = (data.get("username") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

        if len(username) < 3:
            raise ApiError("Username needs at least 3 characters.", field="username")
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ApiError("Enter a valid email address.", field="email")
        if len(password) < 8:
            raise ApiError("Password needs at least 8 characters.", field="password")
        if User.query.filter_by(username=username).first():
            raise ApiError("That username is taken.", status=409, field="username")
        if User.query.filter_by(email=email).first():
            raise ApiError("That email is already registered.", status=409, field="email")

        # First account bootstraps the admin; everyone after is a regular user.
        role = "admin" if User.query.count() == 0 else "user"

        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        return jsonify(user=user.to_dict(), **issue_tokens(user)), 201

    @app.post("/api/auth/login")
    def login():
        data = body()
        identifier = (data.get("username") or data.get("email") or "").strip()
        password = data.get("password") or ""

        user = User.query.filter(
            or_(User.username == identifier, User.email == identifier.lower())
        ).first()
        if not user or not user.check_password(password):
            raise ApiError("Username or password is incorrect.", status=401)

        return jsonify(user=user.to_dict(), **issue_tokens(user))

    @app.post("/api/auth/refresh")
    @jwt_required(refresh=True)
    def refresh():
        user = db.session.get(User, int(get_jwt_identity()))
        if not user:
            raise ApiError("That account no longer exists.", status=401)
        return jsonify(access_token=create_access_token(identity=user))

    @app.get("/api/auth/me")
    @jwt_required()
    def me():
        return jsonify(user=current_user.to_dict(with_counts=True))

    # ---- tasks ----------------------------------------------------------
    @app.get("/api/tasks")
    @jwt_required()
    def list_tasks():
        args = request.args
        query = Task.query

        # Regular users only ever see their own tasks. Admins can opt into
        # the whole board with ?scope=all, or one person with ?user_id=.
        if current_user.is_admin and args.get("scope") == "all":
            if args.get("user_id"):
                query = query.filter(Task.user_id == args.get("user_id", type=int))
        else:
            query = query.filter(Task.user_id == current_user.id)

        if args.get("priority"):
            priorities = [p.strip() for p in args["priority"].split(",") if p.strip()]
            for p in priorities:
                check_choice(p, PRIORITIES, "priority")
            query = query.filter(Task.priority.in_(priorities))

        if args.get("status"):
            statuses = [s.strip() for s in args["status"].split(",") if s.strip()]
            for s in statuses:
                check_choice(s, STATUSES, "status")
            query = query.filter(Task.status.in_(statuses))

        if args.get("q"):
            like = f"%{args['q'].strip()}%"
            query = query.filter(or_(Task.title.ilike(like), Task.description.ilike(like)))

        if args.get("due_after"):
            query = query.filter(Task.deadline >= parse_datetime(args["due_after"], "due_after"))
        if args.get("due_before"):
            query = query.filter(Task.deadline <= parse_datetime(args["due_before"], "due_before"))
        if args.get("has_deadline") in ("true", "1"):
            query = query.filter(Task.deadline.isnot(None))

        if args.get("overdue") in ("true", "1"):
            query = query.filter(
                Task.deadline.isnot(None), Task.deadline < utcnow(), Task.status != "done"
            )

        sort = args.get("sort", "deadline")
        direction = args.get("order", "asc").lower()
        columns = {
            "deadline": Task.deadline,
            "priority": Task.priority_order(),
            "created_at": Task.created_at,
            "updated_at": Task.updated_at,
            "title": Task.title,
        }
        if sort not in columns:
            raise ApiError(f"sort must be one of: {', '.join(columns)}.", field="sort")
        column = columns[sort]
        query = query.order_by(column.desc() if direction == "desc" else column.asc())

        page = max(args.get("page", 1, type=int), 1)
        per_page = min(max(args.get("per_page", 25, type=int), 1), 100)
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify(
            tasks=[t.to_dict(with_owner=current_user.is_admin) for t in pagination.items],
            meta={
                "page": pagination.page,
                "per_page": pagination.per_page,
                "total": pagination.total,
                "pages": pagination.pages,
            },
        )

    @app.post("/api/tasks")
    @jwt_required()
    def create_task():
        data = body()
        title = (data.get("title") or "").strip()
        if not title:
            raise ApiError("Give the task a title.", field="title")

        task = Task(
            title=title[:200],
            description=(data.get("description") or "").strip(),
            priority=check_choice(data.get("priority", "medium"), PRIORITIES, "priority"),
            status=check_choice(data.get("status", "todo"), STATUSES, "status"),
            deadline=parse_datetime(data.get("deadline")),
            user_id=current_user.id,
        )
        db.session.add(task)
        db.session.commit()
        return jsonify(task=task.to_dict()), 201

    @app.get("/api/tasks/<int:task_id>")
    @jwt_required()
    def get_task(task_id):
        return jsonify(task=owned_task(task_id).to_dict(with_owner=current_user.is_admin))

    @app.route("/api/tasks/<int:task_id>", methods=["PATCH", "PUT"])
    @jwt_required()
    def update_task(task_id):
        task = owned_task(task_id)
        data = body()

        if "title" in data:
            title = (data.get("title") or "").strip()
            if not title:
                raise ApiError("Give the task a title.", field="title")
            task.title = title[:200]
        if "description" in data:
            task.description = (data.get("description") or "").strip()
        if "priority" in data:
            task.priority = check_choice(data["priority"], PRIORITIES, "priority")
        if "status" in data:
            task.status = check_choice(data["status"], STATUSES, "status")
        if "deadline" in data:
            task.deadline = parse_datetime(data["deadline"])

        db.session.commit()
        return jsonify(task=task.to_dict())

    @app.delete("/api/tasks/<int:task_id>")
    @jwt_required()
    def delete_task(task_id):
        task = owned_task(task_id)
        db.session.delete(task)
        db.session.commit()
        return jsonify(message="Task deleted.", id=task_id)

    @app.get("/api/tasks/stats")
    @jwt_required()
    def task_stats():
        query = Task.query
        if not (current_user.is_admin and request.args.get("scope") == "all"):
            query = query.filter(Task.user_id == current_user.id)
        tasks = query.all()
        return jsonify(
            total=len(tasks),
            by_status={s: sum(1 for t in tasks if t.status == s) for s in STATUSES},
            by_priority={p: sum(1 for t in tasks if t.priority == p) for p in PRIORITIES},
            overdue=sum(1 for t in tasks if t.is_overdue),
        )

    # ---- admin ----------------------------------------------------------
    @app.get("/api/users")
    @admin_required
    def list_users():
        users = User.query.order_by(User.created_at.asc()).all()
        return jsonify(users=[u.to_dict(with_counts=True) for u in users])

    @app.patch("/api/users/<int:user_id>/role")
    @admin_required
    def set_role(user_id):
        user = db.session.get(User, user_id)
        if not user:
            raise ApiError("No user with that id.", status=404)
        if user.id == current_user.id:
            raise ApiError("You cannot change your own role.", status=409)
        user.role = check_choice(body().get("role"), ROLES, "role")
        db.session.commit()
        return jsonify(user=user.to_dict(with_counts=True))

    @app.delete("/api/users/<int:user_id>")
    @admin_required
    def delete_user(user_id):
        user = db.session.get(User, user_id)
        if not user:
            raise ApiError("No user with that id.", status=404)
        if user.id == current_user.id:
            raise ApiError("You cannot delete your own account here.", status=409)
        db.session.delete(user)  # tasks cascade
        db.session.commit()
        return jsonify(message="User deleted.", id=user_id)


def issue_tokens(user):
    return {
        "access_token": create_access_token(identity=user),
        "refresh_token": create_refresh_token(identity=user),
    }


def owned_task(task_id):
    """Fetch a task the caller is allowed to touch (admins can touch any)."""
    task = db.session.get(Task, task_id)
    if not task:
        raise ApiError("No task with that id.", status=404)
    if task.user_id != current_user.id and not current_user.is_admin:
        raise ApiError("That task belongs to someone else.", status=403)
    return task


# --------------------------------------------------------------------------
# CLI helpers
# --------------------------------------------------------------------------
def register_cli(app):
    @app.cli.command("seed")
    def seed():
        """Create a demo admin, a demo user, and a handful of tasks."""
        from datetime import timedelta as td

        if User.query.filter_by(username="admin").first():
            print("Demo data already present.")
            return

        admin = User(username="admin", email="admin@example.com", role="admin")
        admin.set_password("adminpass123")
        alex = User(username="alex", email="alex@example.com", role="user")
        alex.set_password("alexpass123")
        db.session.add_all([admin, alex])
        db.session.flush()

        now = utcnow()
        samples = [
            ("Ship the invoice export", "urgent", "in_progress", now + td(hours=6), alex),
            ("Review pull request #212", "high", "todo", now + td(days=1), alex),
            ("Book the dentist", "low", "todo", now + td(days=9), alex),
            ("Rotate API keys", "high", "todo", now - td(hours=3), admin),
            ("Write onboarding docs", "medium", "done", now - td(days=2), admin),
        ]
        for title, priority, status, deadline, owner in samples:
            db.session.add(
                Task(
                    title=title,
                    description="",
                    priority=priority,
                    status=status,
                    deadline=deadline,
                    user_id=owner.id,
                )
            )
        db.session.commit()
        print("Seeded: admin/adminpass123 and alex/alexpass123")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
