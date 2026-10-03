"""Transparent keyword sentiment scorer for energy-market headlines.

HONESTY NOTE: this is a simple, explainable HEURISTIC - not a trained model and
not an LLM. Scores are labeled "keyword heuristic" in the UI. It cannot detect
sarcasm or context (e.g. "prices jump" is good for producers, bad for consumers).
Phase 7 upgrades this with a proper News Sentiment Agent.

score = (positive_hits - negative_hits) / (positive_hits + negative_hits + 1)
The "+1" keeps one stray word from producing a full +/-1.0 score.
Range: -1.0 .. +1.0. Deterministic: same headline -> same score.
"""
import re

# Matched as word PREFIXES, so "disrupt" covers disrupt/disrupted/disruption.
_NEGATIVE = (
    "shutdown", "shut down", "shut-in", "disrupt", "outage", "damage", "storm", "hurricane",
    "flood", "evacuat", "halt", "fire", "explosion", "spill", "risk", "threat", "warn",
    "fall", "fell", "drop", "plung", "slump", "declin", "slid", "tumbl", "sink", "loss",
    "cut", "slash", "weak", "concern", "fear", "crisis", "shortage", "suspend",
)
_POSITIVE = (
    "surg", "rall", "gain", "jump", "climb", "rise", "rising", "rose", "beat", "record",
    "growth", "profit", "strong", "boost", "upgrad", "recover", "resum", "firm", "advance",
    "optimis", "bullish",
)

_WORD = re.compile(r"[a-z][a-z\-]*")


def _hits(text: str, stems: tuple[str, ...]) -> int:
    lowered = text.lower()
    tokens = _WORD.findall(lowered)
    count = 0
    for stem in stems:
        if " " in stem:                       # multi-word phrase
            count += lowered.count(stem)
        else:
            count += sum(1 for t in tokens if t.startswith(stem))
    return count


def score_text(text: str) -> float:
    pos, neg = _hits(text, _POSITIVE), _hits(text, _NEGATIVE)
    return round((pos - neg) / (pos + neg + 1), 3)


def label(score: float) -> str:
    # Same documented thresholds as the demo feed, so labels are comparable.
    if score > 0.15:
        return "positive"
    if score < -0.15:
        return "negative"
    return "neutral"


_ASSET_KEYWORDS = (
    ("exxon", "XOM"), ("chevron", "CVX"),
    ("natural gas", "Natural gas"), ("lng", "Natural gas"),
    ("crude", "Crude oil"), ("brent", "Crude oil"), ("wti", "Crude oil"), ("oil", "Crude oil"),
)


def related_asset(headline: str) -> str:
    """Tag a headline with the asset it mentions (first keyword match wins)."""
    lowered = headline.lower()
    tokens = set(_WORD.findall(lowered))
    for keyword, asset in _ASSET_KEYWORDS:
        if (" " in keyword and keyword in lowered) or keyword in tokens:
            return asset
    return "Energy"
