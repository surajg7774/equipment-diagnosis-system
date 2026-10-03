"""The technician access code: a small gate in front of two actions, NOT a login system.

Only "Verify/Confirm" (``POST /tickets/{id}/confirm``) and "Correct" (``POST /tickets/{id}/correct``) can
teach the knowledge base what is verified, so only those two need ``X-Technician-Code``. Diagnosing, thumbs
up/down, history, stats and everything else stay open to everyone, exactly as before.

  * ``TECHNICIAN_ACCESS_CODE`` unset or blank  -> the gate is OFF and those two endpoints behave as they always did
    (the safe default for local runs and tests, and the instant kill switch: unset it to disable).
  * set                                        -> the header must match; otherwise 401.

It is one shared secret, so there are no user accounts, no tokens and no expiry, and it cannot say WHO verified
something. Pick a long random code: nothing slows down repeated guessing (see the README limitations).
"""

import hmac
import logging
from enum import Enum

from pydantic import SecretStr

logger = logging.getLogger(__name__)

# Shorter codes still work, but the server says so at startup: nothing rate-limits wrong guesses.
MIN_RECOMMENDED_LENGTH = 12


class CodeCheck(str, Enum):
    NOT_REQUIRED = "not_required"  # no code configured: the gate is off
    OK = "ok"
    MISSING = "missing"  # a code is required and none (or a blank one) was sent
    WRONG = "wrong"


def check_technician_code(provided: str | None, expected: SecretStr | None) -> CodeCheck:
    """Compare what the client sent with the configured code, in constant time."""
    if expected is None:
        return CodeCheck.NOT_REQUIRED
    candidate = (provided or "").strip()
    if not candidate:
        return CodeCheck.MISSING
    # Compare BYTES: hmac.compare_digest refuses non-ASCII str, and a stray character must be "wrong", not a 500.
    if hmac.compare_digest(candidate.encode("utf-8"), expected.get_secret_value().encode("utf-8")):
        return CodeCheck.OK
    return CodeCheck.WRONG


def code_problems(expected: SecretStr | None) -> list[str]:
    """Things about the CONFIGURED code worth warning about (never includes the code itself)."""
    if expected is None:
        return []
    code = expected.get_secret_value()
    problems = []
    if len(code) < MIN_RECOMMENDED_LENGTH:
        problems.append(
            f"it is only {len(code)} characters; use at least {MIN_RECOMMENDED_LENGTH} (wrong guesses are not rate limited)"
        )
    if not (code.isascii() and code.isprintable()):
        problems.append("it contains characters a browser cannot send in a header; use letters, digits and hyphens")
    return problems


def log_technician_code_status(expected: SecretStr | None) -> None:
    """One startup line saying whether Verify/Correct are protected (the value is never logged)."""
    if expected is None:
        logger.warning(
            "technician_code_not_configured",
            extra={"hint": "Verify, Confirm and Correct are open to everyone. Set TECHNICIAN_ACCESS_CODE to protect them."},
        )
        return
    logger.info("technician_code_configured")
    for problem in code_problems(expected):
        logger.warning("technician_code_weak", extra={"problem": problem})
