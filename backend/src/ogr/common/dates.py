"""Shared date normalizer for OGR — used by both ingestion and P3 entity linking.

Source spec: TECHNICAL-SPEC §2.3, §3 (Q2/Q3 date constraints)
Plan: implementation-plan-AGENT.md Group 2 (one normalizer, no second copy)

Measured corpus characteristics:
  - Two date fields: 'date' (57.9%) and 'dates' (41.1%)
  - Heterogeneous formats; only 81% carry a year
  - multi_hop + temporal = 50/100 public questions

Normalizes raw date strings into {year, month, day_start, day_end} INT fields
matching the OlympicEvent schema attributes:
  date_year, date_month, date_day_start, date_day_end
"""

from __future__ import annotations

import re
from typing import Optional

# Month name → number mapping
MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


class NormalizedDate:
    """Parsed date with int fields matching the OlympicEvent schema."""

    def __init__(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
        day_start: Optional[int] = None,
        day_end: Optional[int] = None,
    ) -> None:
        self.year = year
        self.month = month
        self.day_start = day_start
        self.day_end = day_end

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"NormalizedDate(year={self.year}, month={self.month}, "
            f"day_start={self.day_start}, day_end={self.day_end})"
        )

    def to_dict(self) -> dict:
        return {
            "date_year": self.year,
            "date_month": self.month,
            "date_day_start": self.day_start,
            "date_day_end": self.day_end,
        }


def normalize_date(raw: Optional[str]) -> NormalizedDate:
    """Parse a raw date string from the corpus into NormalizedDate.

    Handles formats observed in the corpus:
      - "12 August 2004"
      - "12–14 August 2004"
      - "August 12, 2004"
      - "2004-08-12"
      - "12 August – 1 September 2004"
      - "12 August 2004 – 14 August 2004"
    """
    if not raw or not raw.strip():
        return NormalizedDate()

    raw = raw.strip()
    result = NormalizedDate()

    # Try ISO format: YYYY-MM-DD
    iso_match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw)
    if iso_match:
        result.year = int(iso_match.group(1))
        result.month = int(iso_match.group(2))
        result.day_start = int(iso_match.group(3))
        return result

    # Normalize unicode dashes
    raw_norm = raw.replace("–", "-").replace("—", "-")

    # Extract year (4-digit)
    year_match = re.search(r"\b(\d{4})\b", raw_norm)
    if year_match:
        result.year = int(year_match.group(1))

    # Extract month name
    for name, num in MONTH_MAP.items():
        if re.search(r"\b" + name + r"\b", raw_norm, re.IGNORECASE):
            result.month = num
            break

    # Extract day numbers: "12" or "12-14" or "12 - 14"
    day_range = re.search(r"\b(\d{1,2})\s*[-]\s*(\d{1,2})\b", raw_norm)
    if day_range:
        result.day_start = int(day_range.group(1))
        result.day_end = int(day_range.group(2))
    else:
        day_match = re.search(r"\b(\d{1,2})\b", raw_norm)
        if day_match:
            day_val = int(day_match.group(1))
            # Avoid capturing the year as a day
            if day_val <= 31:
                result.day_start = day_val

    return result


def parse_games_year(games_id: str) -> Optional[int]:
    """Extract year from games_id like '2016-Summer' or '1996-Atlanta'."""
    m = re.match(r"(\d{4})", games_id)
    return int(m.group(1)) if m else None
