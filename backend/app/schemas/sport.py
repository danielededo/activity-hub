"""Sport catalogue response model."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class SportRead(BaseModel):
    """What the dashboard needs to know to show a sport.

    The file-format aliases stay on the server: only the parsers use them.
    """

    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    rate: Literal["pace", "speed"]
    cadence_unit: Literal["spm", "rpm"]
    color: Literal["cycling", "running", "hiking", "other"]
