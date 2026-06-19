"""
Schema module - Export BaseSchema for imports in main.py.
"""

from pydantic import BaseModel


class BaseSchema(BaseModel):
    """
    Base Pydantic model for all API schemas.
    
    Provides common configuration for Pydantic v2 models:
    - Config dict for serialization
    - Type hints support
    - Validation settings
    """
    
    class Config:
        from_attributes = True
