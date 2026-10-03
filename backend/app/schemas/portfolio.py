from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import DataMeta

Sector = Literal[
    "Energy", "Technology", "Financials", "Healthcare",
    "Industrials", "Utilities", "Consumer", "Other",
]


class HoldingIn(BaseModel):
    """One holding as the user submits it. Validation = input sanitising."""

    symbol: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9.\-=^]+$")
    name: str = Field(min_length=1, max_length=80)
    sector: Sector
    weight_pct: float = Field(gt=0, le=100)

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.upper()

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = " ".join(v.split())  # collapse stray whitespace/newlines
        if any(c in v for c in "<>"):  # no HTML-ish characters
            raise ValueError("name contains invalid characters")
        return v


class PortfolioIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    total_value: float = Field(gt=0, le=1e12)
    holdings: list[HoldingIn] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def weights_sum_to_100(self) -> "PortfolioIn":
        total = sum(h.weight_pct for h in self.holdings)
        if abs(total - 100) > 0.01:
            raise ValueError(f"holding weights must sum to 100 (got {total:.2f})")
        return self


class Holding(BaseModel):
    symbol: str
    name: str
    sector: Sector
    weight_pct: float
    value_usd: float  # calculated: total_value * weight


class SectorExposure(BaseModel):
    sector: Sector
    weight_pct: float
    value_usd: float


class PortfolioResponse(BaseModel):
    meta: DataMeta
    name: str
    total_value: float
    holdings: list[Holding]
    sector_exposure: list[SectorExposure]
    energy_exposure_pct: float
