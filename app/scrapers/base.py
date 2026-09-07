"""
Scraper base — every scraper returns a validated Pydantic row or raises.
ScraperResult carries the row + source health so callers never have to
catch-and-guess; they just check result.ok.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional
from pydantic import BaseModel


@dataclass
class ScraperResult:
    source: str
    ok: bool
    row: Optional[BaseModel] = None  # validated Pydantic schema instance
    error: Optional[str] = None
    rows_quarantined: int = 0

    @classmethod
    def success(cls, source: str, row: BaseModel) -> "ScraperResult":
        return cls(source=source, ok=True, row=row)

    @classmethod
    def failure(
        cls, source: str, error: str, rows_quarantined: int = 1
    ) -> "ScraperResult":
        return cls(
            source=source, ok=False, error=error, rows_quarantined=rows_quarantined
        )
