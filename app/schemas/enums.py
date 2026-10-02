"""Enums shared by schemas, models and services."""

from enum import Enum


class Severity(str, Enum):
    """How urgent an issue is. ``str`` mixin => serialises as "low"/"medium"/"high"."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DiagnosisBasis(str, Enum):
    """What the LLM's diagnosis was grounded on."""

    SIMILAR_CASES = "similar_cases"  # a close match existed; cases were given to the LLM
    GENERAL_REASONING = "general_reasoning"  # no close match; the LLM used its own knowledge
