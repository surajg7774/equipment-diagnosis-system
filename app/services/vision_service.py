"""Image-based diagnosis: interface + PLACEHOLDER implementation.

>>> THIS MODULE IS A SWAPPABLE PLACEHOLDER. <<<

The API only knows about the ``VisionService`` interface below.  To plug in a
real CNN / transfer-learning model (e.g. a fine-tuned ResNet or EfficientNet):

  1. Create ``class CnnVisionService(VisionService)`` that loads the model in
     ``__init__`` and implements ``analyze(image_bytes) -> VisionPrediction``.
  2. Change the single line in ``app/main.py`` (lifespan) that constructs
     ``PlaceholderVisionService()`` to construct your class.

No route, schema or test of the API layer has to change.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.exceptions import (
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedImageTypeError,
)
from app.schemas.enums import Severity


@dataclass(frozen=True)
class VisionPrediction:
    """What any vision model must return."""

    label: str
    confidence: float
    severity: Severity
    recommended_action: str
    model_name: str
    is_placeholder: bool


class VisionService(ABC):
    """Interface every image-diagnosis model implements."""

    @abstractmethod
    def analyze(self, image_bytes: bytes) -> VisionPrediction:
        """Classify the fault visible in an (already validated) image."""


# ---------------------------------------------------------------------------
# Upload validation (independent of which model is used)
# ---------------------------------------------------------------------------
# "Magic bytes": the first bytes of a file identify its true format, which is
# more trustworthy than the filename or the client-supplied Content-Type.
_IMAGE_SIGNATURES: dict[str, bytes] = {
    "jpeg": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
}


def validate_image_bytes(data: bytes, max_bytes: int) -> str:
    """Check size and format of an upload; return the detected format.

    Raises ``InvalidImageError`` (empty), ``ImageTooLargeError`` or
    ``UnsupportedImageTypeError``.
    """
    if not data:
        raise InvalidImageError("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ImageTooLargeError(f"Image exceeds the {max_bytes // (1024 * 1024)} MB size limit.")

    for fmt, signature in _IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return fmt
    # WebP is "RIFF....WEBP"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise UnsupportedImageTypeError("Unsupported image type. Upload a JPEG, PNG or WebP file.")


# ---------------------------------------------------------------------------
# Placeholder model
# ---------------------------------------------------------------------------
# label -> (severity, recommended action)
_PLACEHOLDER_LABELS: dict[str, tuple[Severity, str]] = {
    "corrosion": (
        Severity.MEDIUM,
        "Clean the affected area, apply a corrosion inhibitor and schedule a detailed inspection.",
    ),
    "oil_leak": (
        Severity.HIGH,
        "Isolate the equipment, find and repair the leak source, and clean up spilled oil.",
    ),
    "cracked_housing": (
        Severity.HIGH,
        "Take the equipment out of service and replace or weld-repair the housing.",
    ),
    "normal_wear": (
        Severity.LOW,
        "No immediate action; note the condition and re-inspect at the next scheduled service.",
    ),
}


class PlaceholderVisionService(VisionService):
    """Stand-in model that performs NO real image analysis.

    It hashes the image bytes and uses the hash to pick one of a few labels, so
    the same image always yields the same answer (handy for demos and tests).
    The result is flagged ``is_placeholder=True`` and the confidence is a fixed
    0.5 so nobody mistakes it for a genuine prediction.
    """

    MODEL_NAME = "placeholder-vision-v0"

    def analyze(self, image_bytes: bytes) -> VisionPrediction:
        labels = sorted(_PLACEHOLDER_LABELS)
        digest = hashlib.sha256(image_bytes).digest()
        label = labels[digest[0] % len(labels)]
        severity, action = _PLACEHOLDER_LABELS[label]
        return VisionPrediction(
            label=label,
            confidence=0.5,
            severity=severity,
            recommended_action=action,
            model_name=self.MODEL_NAME,
            is_placeholder=True,
        )
