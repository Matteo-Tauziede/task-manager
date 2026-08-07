"""Extension singletons.

Kept in their own module so `models.py` can import `db` without importing
`app.py` (which would create a circular import).
"""

from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
jwt = JWTManager()
