"""Enums shared by schemas, models and services."""

from enum import Enum


class Severity(str, Enum):
    """How urgent an issue is. ``str`` mixin => serialises as "low"/"medium"/"high"."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewStatus(str, Enum):
    """Where a ticket is in the human-verification workflow."""

    PENDING = "pending"  # nobody has checked the AI's diagnosis yet
    CONFIRMED = "confirmed"  # a technician confirmed the AI's diagnosis was correct
    CORRECTED = "corrected"  # a technician supplied the real root cause and fix


class ReviewPriority(str, Enum):
    """How urgently a pending ticket needs a human look (medium/high severity first)."""

    HIGH = "high"
    LOW = "low"


class SessionStatus(str, Enum):
    """Where an iterative diagnosis session is."""

    IN_PROGRESS = "in_progress"  # solutions are still being tried
    RESOLVED = "resolved"  # the user said a solution worked
    ABANDONED = "abandoned"  # every allowed attempt failed: the user is told to escalate to a human


class KnowledgeOutcome(str, Enum):
    """Whether a knowledge-base record built from user feedback describes a fix that worked.

    Seed records carry no outcome: they are curated resolved cases and count as working fixes.
    """

    VERIFIED_FIX = "verified_fix"  # thumbs up / technician confirmed or corrected: this fix worked
    FAILED_FIX = "failed_fix"  # thumbs down: this diagnosis + fix was suggested and did NOT work


class DiagnosisBasis(str, Enum):
    """What the LLM's diagnosis was grounded on."""

    SIMILAR_CASES = "similar_cases"  # a close match existed; cases were given to the LLM
    GENERAL_REASONING = "general_reasoning"  # no close match; the LLM used its own knowledge
