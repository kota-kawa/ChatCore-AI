"""SQLAlchemy model foundation shared by the application and Alembic."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every PostgreSQL table owned by ChatCore."""
