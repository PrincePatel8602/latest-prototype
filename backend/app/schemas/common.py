from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DataMeta(BaseModel):
    """Attached to EVERY data response so the UI can always label its origin.

    source: "live" = real external API, "demo" = built-in sample data,
            "user" = values typed in by the user (e.g. their portfolio).
    """

    source: Literal["live", "demo", "user"]
    notice: str | None = None  # human-readable explanation shown in the UI
    as_of: datetime
