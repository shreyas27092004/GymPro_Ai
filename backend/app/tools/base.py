# app/tools/base.py
from pydantic import BaseModel, ConfigDict


class BaseArgs(BaseModel):
    """
    Base class for all tool argument schemas.
    extra='forbid' strictly rejects unexpected arguments and prevents parameter injection.
    """
    model_config = ConfigDict(extra="forbid")


class EmptyArgs(BaseArgs):
    """Schema for tools requiring no input arguments."""
    pass
