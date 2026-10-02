"""Severity classification: a transparent, rule-based keyword heuristic.

Why a heuristic and not ML?  Severity drives safety decisions, so it must be
predictable and explainable: for any input we can show exactly which words
produced the score.  (It could later be replaced by a trained classifier
behind the same ``classify_severity`` signature.)

HOW IT WORKS
------------
1. Look for known "risk words" in the technician's text.  Each belongs to a tier:

       CRITICAL  (+4)  danger to people/property: smoke, fire, sparks, burning
                       smell, overheating, electric shock, gas/refrigerant leak...
       SERIOUS   (+2)  real mechanical/electrical failure: grinding, leaking,
                       vibration, won't start, tripped breaker, tear/crack...
       MINOR     (+1)  annoyance-level symptoms: noise, slow, warm, drip,
                       jam, flicker, smudge, offline...
       MITIGATING (-1) words that downplay it: slight, minor, occasional...

2. Each distinct risk word counts once (repeating "leak leak leak" doesn't
   inflate the score).  A word is ignored if negated ("no smoke", "not leaking").

3. Add up the points (never below 0) and map to a level:

       score >= 4  -> HIGH      (so one CRITICAL word is enough on its own)
       score >= 2  -> MEDIUM
       otherwise   -> LOW

Worked example::

    "pump making loud grinding noise and leaking oil"
      grinding (+2) + leaking (+2) + loud/noise (+1) = 5  -> HIGH

KNOWN LIMITATIONS: it only understands English keywords, handles negation only
for the simple "no/not/without X" pattern, and ignores context beyond that.
"""

import re
from dataclasses import dataclass

from app.schemas.enums import Severity

CRITICAL_WEIGHT = 4
SERIOUS_WEIGHT = 2
MINOR_WEIGHT = 1
MITIGATING_WEIGHT = -1

HIGH_THRESHOLD = 4
MEDIUM_THRESHOLD = 2

# --- Keyword tiers: (display label, regex) --------------------------------
# Regexes run on lower-cased text. \b = word boundary, so "fire" does not match
# inside "misfire"/"fireplace" prefixes unintentionally.
_CRITICAL_TERMS: list[tuple[str, str]] = [
    ("smoke", r"\bsmok(?:e|es|ing|y)\b"),
    ("fire", r"\b(?:fire|flames?|burst into flames)\b"),
    ("sparks", r"\bspark(?:s|ing|ed)?\b"),
    ("burning", r"\b(?:burn(?:s|ing|ed|t)?)\b"),
    ("explosion", r"\bexplo(?:de|des|ded|sion)\b"),
    ("electric shock", r"\b(?:electric(?:al)? shock|electrocut\w*|shocked)\b"),
    ("short circuit", r"\bshort[- ]?circuit\w*\b"),
    ("gas leak", r"\bgas leak\w*\b"),
    ("overheating", r"\b(?:overheat\w*|over[- ]heat\w*)\b"),
    ("chemical/refrigerant smell", r"\b(?:chemical|refrigerant)\s+(?:smell|odou?r|fumes?)\b|\bfumes?\b"),
]

_SERIOUS_TERMS: list[tuple[str, str]] = [
    ("grinding", r"\bgrind(?:s|ing)?\b"),
    ("leak", r"\bleak\w*\b"),
    ("vibration", r"\bvibrat\w*\b"),
    ("banging/knocking", r"\b(?:bang\w*|knock\w*|clunk\w*)\b"),
    ("won't start", r"\b(?:won'?t|will not|wont|does not|doesn'?t|fails? to|failed to|cannot|can'?t|unable to)\s+(?:start|turn on|power on)\w*"),
    ("no power", r"\bno power\b|\bnot starting\b|\bdead\b"),
    ("tripping", r"\btrip(?:s|ped|ping)?\b"),
    ("seized", r"\bseiz\w*\b"),
    ("torn/cracked", r"\b(?:tear|torn|ripped|crack\w*|fray\w*|burst)\b"),
    ("squealing", r"\bsqueal\w*\b"),
    ("shutdown", r"\bshut(?:s|ting)?[ -]?down\b"),
]

_MINOR_TERMS: list[tuple[str, str]] = [
    ("noise", r"\b(?:noise|noisy|loud|rattl\w*|squeak\w*|hum(?:s|ming)?)\b"),
    ("slow/weak", r"\b(?:slow|slowly|weak|low pressure|low flow|reduced)\b"),
    ("warm/hot", r"\b(?:warm|hot)\b"),
    ("drip", r"\bdrip\w*\b"),
    ("jam", r"\bjam(?:s|med|ming)?\b"),
    ("flicker", r"\bflicker\w*\b"),
    ("print defect", r"\b(?:smudg\w*|streak\w*|smear\w*)\b"),
    ("offline/error", r"\b(?:offline|error|unstable|intermittent\w*)\b"),
]

_MITIGATING_TERMS: list[tuple[str, str]] = [
    ("slight/minor", r"\b(?:slight(?:ly)?|minor|small|little|a bit)\b"),
    ("occasional", r"\boccasional(?:ly)?\b"),
]

# "no smoke", "not leaking", "without sparks", "doesn't leak" -> not a symptom.
_NEGATION_BEFORE = re.compile(r"(?:\bno|\bnot|\bwithout|\bnever|n't)\s+(?:\w+\s+)?$")

_TIERS = (
    (_CRITICAL_TERMS, CRITICAL_WEIGHT),
    (_SERIOUS_TERMS, SERIOUS_WEIGHT),
    (_MINOR_TERMS, MINOR_WEIGHT),
    (_MITIGATING_TERMS, MITIGATING_WEIGHT),
)


@dataclass(frozen=True)
class SeverityAssessment:
    """Result of classification, kept explainable for logs and debugging."""

    level: Severity
    score: int
    matched_terms: tuple[str, ...]


def _is_negated(text: str, match_start: int) -> bool:
    """True if the matched word is preceded by 'no', 'not', 'without'..."""
    preceding = text[max(0, match_start - 20) : match_start]
    return bool(_NEGATION_BEFORE.search(preceding))


def score_severity(text: str) -> tuple[int, tuple[str, ...]]:
    """Return ``(score, matched_term_labels)`` for ``text`` (steps 1-2 above)."""
    normalised = text.lower().replace("’", "'")  # curly -> straight apostrophe
    score = 0
    matched: list[str] = []

    for terms, weight in _TIERS:
        for label, pattern in terms:
            hits = [m for m in re.finditer(pattern, normalised) if not _is_negated(normalised, m.start())]
            if hits:  # count each distinct term once
                score += weight
                matched.append(label)

    return max(score, 0), tuple(matched)


def level_for_score(score: int) -> Severity:
    """Map a numeric score to LOW / MEDIUM / HIGH (step 3 above)."""
    if score >= HIGH_THRESHOLD:
        return Severity.HIGH
    if score >= MEDIUM_THRESHOLD:
        return Severity.MEDIUM
    return Severity.LOW


_SEVERITY_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}


def combine_severity(heuristic_level: Severity, llm_level: Severity) -> Severity:
    """Final severity = the MORE severe of the keyword heuristic and the LLM's opinion.

    Why take the max?  The two are wrong in opposite ways.  The heuristic only
    knows its keyword list, so it misses novel problems the LLM can recognise
    ("chain snapped").  The LLM is a small, non-deterministic model that could
    talk itself into downplaying something dangerous ("smoke" -> "low").  For a
    safety-relevant label, over-warning is the cheaper mistake, so each acts as
    a floor for the other.
    """
    return max(heuristic_level, llm_level, key=_SEVERITY_RANK.__getitem__)


def classify_severity(text: str) -> SeverityAssessment:
    """Classify the severity of a free-text issue description."""
    score, matched = score_severity(text)
    return SeverityAssessment(level=level_for_score(score), score=score, matched_terms=matched)
