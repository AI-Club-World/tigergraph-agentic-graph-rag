"""Surface forms for the injection harness (ROUND2-DESIGN.md §8).

Several template families per statement, so no reasoning component can
lean on one wording: claims are read from the record's key/value block
(datasets/block_records.py), and the prose varies freely. The sources are
fictional and every generated record is marked `synthetic`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DATE_FORMATS", "PROSE", "QUESTIONS", "SOURCES", "Source"]


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    cls: str
    reliability: float


SOURCES: dict[str, list[Source]] = {
    "official": [
        Source("src:results-office", "Olympic Results Office", "official", 0.95),
        Source("src:federation-bulletin", "World Federation Bulletin", "official", 0.9),
    ],
    "news": [
        Source("src:sports-wire", "Global Sports Wire", "news", 0.8),
        Source("src:athletics-daily", "Daily Athletics Report", "news", 0.75),
        Source("src:games-herald", "Games Herald", "news", 0.7),
    ],
    "blog": [
        Source("src:fan-zone", "Fan Zone Blog", "blog", 0.4),
        Source("src:rumour-mill", "Sports Rumour Mill", "blog", 0.3),
    ],
    "forum": [
        Source("src:olympics-forum", "Olympics Discussion Forum", "forum", 0.3),
    ],
}

# strftime-free formats: (day, month name, year) -> text
DATE_FORMATS = (
    lambda d, m, y: f"{d} {m} {y}",
    lambda d, m, y: f"{m} {d}, {y}",
    lambda d, m, y: f"{d} {m[:3]} {y}",
)

# Prose families per statement kind. Placeholders: {event} (event part of the
# title), {title}, {old}, {new}, {value}, {source}, {when}.
PROSE: dict[str, list[str]] = {
    # Result revisions are neutral: a timing or judging review, never an
    # accusation. The events and names are real; a generated statement must
    # not attribute misconduct to a real person.
    "reallocation": [
        "After a review of the timing data, the result of the {event} was corrected and the gold "
        "medal now goes to {new}.",
        "The official result of the {event} was revised following a judging review; {new} is now "
        "listed as the gold medallist.",
        "A results review of the {event} amended the standings, placing {new} first ahead of {old}.",
    ],
    "reinstatement": [
        "A further review of the {event} restored the original result, and {old} is again listed "
        "as the gold medallist.",
        "The earlier correction to the {event} result was itself revised; the gold medal is once "
        "more credited to {old}.",
    ],
    "revision_rumour": [
        "Unconfirmed reports suggest the {event} result may be revised, "
        "with {new} reportedly in line for gold.",
        "According to some fans, {new} could be upgraded to gold in the {event}; "
        "officials have not confirmed it.",
    ],
    "attendance": [
        "{value} spectators attended the final of the {event}.",
        "The final of the {event} drew a crowd of {value}.",
        "A total of {value} people watched the {event} final in the stands.",
    ],
    "attendance_hedged": [
        "About {value} spectators are believed to have attended the final of the {event}, "
        "according to early estimates.",
        "Unconfirmed figures suggest a crowd of roughly {value} for the {event} final.",
        "The final of the {event} reportedly drew around {value} spectators; the figure is provisional.",
    ],
    "competitors": [
        "{value} athletes started the {event}.",
        "The field for the {event} numbered {value} competitors.",
        "In total, {value} competitors took part in the {event}.",
    ],
}

# Question phrasings per intent. The detector (pipelines/temporal.py) is
# general; these are not tuned to it, and a test checks each one parses
# into the scope the ground truth assumes.
QUESTIONS: dict[str, list[str]] = {
    "gold_latest": [
        "Who is currently credited with the gold medal in {title}?",
        "After all revisions, who holds the gold medal in {title}?",
        "Who is the latest recognised gold medallist of {title}?",
    ],
    "gold_original": [
        "Who was originally awarded the gold medal in {title}?",
        "Who initially won the gold medal in {title}, before any revision?",
    ],
    "gold_as_of": [
        "As of {year}, who was listed as the gold medallist of {title}?",
        "Who held the gold medal in {title} as of {year}?",
    ],
    "attendance": [
        "What was the attendance at the final of {title}?",
        "How many spectators attended the final of {title}?",
    ],
    "competitors": [
        "How many competitors took part in {title}?",
        "How many athletes competed in {title}?",
    ],
}
