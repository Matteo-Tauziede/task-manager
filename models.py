"""Database models: User and Task."""

from datetime import datetime, timezone

from sqlalchemy import case
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db

PRIORITIES = ("low", "medium", "high", "urgent")
STATUSES = ("todo", "in_progress", "done")
ROLES = ("user", "admin")

# Used to sort by "how urgent", not alphabetically.
PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}


def utcnow():
    """Naive UTC timestamp (SQLite does not store timezones)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    """Render a naive-UTC datetime as an ISO 8601 string the browser understands."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="user")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    tasks = db.relationship(
        "Task",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # --- password helpers -------------------------------------------------
    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_admin(self):
        return self.role == "admin"

    def to_dict(self, with_counts=False):
        data = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "created_at": iso(self.created_at),
        }
        if with_counts:
            data["task_count"] = self.tasks.count()
        return data

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    priority = db.Column(db.String(16), nullable=False, default="medium", index=True)
    status = db.Column(db.String(16), nullable=False, default="todo", index=True)
    deadline = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner = db.relationship("User", back_populates="tasks")

    @classmethod
    def priority_order(cls):
        """SQL expression that sorts urgent -> low."""
        return case(PRIORITY_RANK, value=cls.priority, else_=99)

    @property
    def is_overdue(self):
        return (
            self.deadline is not None
            and self.status != "done"
            and self.deadline < utcnow()
        )

    def to_dict(self, with_owner=False):
        data = {
            "id": self.id,
            "title": self.title,
            "description": self.description or "",
            "priority": self.priority,
            "status": self.status,
            "deadline": iso(self.deadline),
            "is_overdue": self.is_overdue,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "user_id": self.user_id,
        }
        if with_owner and self.owner is not None:
            data["owner"] = self.owner.username
        return data

    def __repr__(self):
        return f"<Task {self.id} {self.title!r} {self.priority}>"
