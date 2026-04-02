"""
SQLAlchemy declarative base.

This module contains only the Base class to avoid circular imports.
All models should import Base from here.
"""
from sqlalchemy.orm import declarative_base

Base = declarative_base()
