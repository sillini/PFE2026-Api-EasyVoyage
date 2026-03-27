"""
SQLAlchemy declarative base shared by all models.
Import Base here and let each model file extend it.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass