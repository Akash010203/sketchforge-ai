"""Shared strict Pydantic base for domain contracts."""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Reject unknown fields and validate assignments for editable contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
