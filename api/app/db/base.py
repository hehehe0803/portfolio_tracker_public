"""
SQLAlchemy Base Model.

Defines the declarative base class for all ORM models.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.
    
    Provides common functionality and metadata for model declarations.
    All models should inherit from this class.
    
    Example:
        class User(Base):
            __tablename__ = "users"
            
            id: Mapped[int] = mapped_column(primary_key=True)
            username: Mapped[str] = mapped_column(String(50), unique=True)
    """
    
    pass
