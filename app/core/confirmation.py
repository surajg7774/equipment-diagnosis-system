"""When is a confirmed fix "verified", and when is it only "provisional"? (pure functions, no I/O)

A single click must not be able to teach the knowledge base something it then trusts. Each confirmation
has a weight, a fix needs a minimum total to be *verified*, and anything below that is *provisional*:
still retrieved (so the demo and the learning loop work), but labelled as such and ranked below verified fixes.

    end user's click (thumbs up, "Yes, it's fixed")  -> weight 1
    technician's review (Confirm or Correct)         -> weight 2   (the expert check the system always relied on)

    MIN_CONFIRMATIONS_TO_VERIFY = 2 (default):  a user's click alone  -> 1 -> provisional
                                                a technician's review -> 2 -> verified
                                                user + technician     -> 3 -> verified
    MIN_CONFIRMATIONS_TO_VERIFY = 1:            anything verifies at once = the behaviour before this safeguard
    MIN_CONFIRMATIONS_TO_VERIFY = 3:            needs BOTH a user and a technician

Each *source* counts once however many times it clicks: the system has no user identity, so a user who
uses both the thumbs and the session "Yes" is still one person. Two end users confirming the same fix on two
different tickets are not pooled: there is no reliable way to tell that two tickets' fixes are the same fix.
"""

from collections.abc import Iterable

from app.schemas.enums import ConfirmationSource, FixVerification

CONFIRMATION_WEIGHTS: dict[str, int] = {
    ConfirmationSource.USER.value: 1,
    ConfirmationSource.TECHNICIAN.value: 2,
}
DEFAULT_MIN_CONFIRMATIONS = 2


def effective_sources(sources: Iterable[str] | None, reviewed: bool) -> set[str]:
    """The sources that have confirmed a ticket's fix.

    Tickets reviewed BEFORE this safeguard existed have no recorded sources; they were verified under the old
    rule, so they keep that status (as a technician review) instead of being quietly demoted.
    """
    if sources:
        return {s for s in sources if s in CONFIRMATION_WEIGHTS}
    return {ConfirmationSource.TECHNICIAN.value} if reviewed else set()


def confirmation_count(sources: Iterable[str]) -> int:
    """Total confirmation weight: each distinct source counts once."""
    return sum(CONFIRMATION_WEIGHTS[s] for s in set(sources) if s in CONFIRMATION_WEIGHTS)


def verification_for(count: int, minimum: int = DEFAULT_MIN_CONFIRMATIONS) -> FixVerification:
    return FixVerification.VERIFIED if count >= minimum else FixVerification.PROVISIONAL
