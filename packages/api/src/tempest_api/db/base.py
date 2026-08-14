"""Declarative base shared by every model and by Alembic's target metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
