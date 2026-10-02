"""Domain-specific exceptions.

Services and the API layer raise these; a single handler in ``app/main.py``
turns them into consistent JSON error responses.  This keeps HTTP concerns
out of the business logic.
"""


class AppError(Exception):
    """Base class for errors that are safe to show to the client."""

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TicketNotFoundError(AppError):
    status_code = 404
    code = "ticket_not_found"


class KnowledgeBaseEmptyError(AppError):
    """Vector store has no records, i.e. the seed script has not been run."""

    status_code = 503
    code = "knowledge_base_empty"


class LLMUnavailableError(AppError):
    """The LLM backend could not be reached or could not serve the request.

    The client-facing message is deliberately generic; the specific cause
    (Ollama not running, model not pulled, timeout...) is written to the logs.
    """

    status_code = 503
    code = "llm_unavailable"


class LLMResponseError(AppError):
    """The LLM answered, but its output was not a usable diagnosis."""

    status_code = 502
    code = "llm_bad_response"


class VisionUnavailableError(AppError):
    """The image-analysis backend could not be reached, is rate limited, or is switched off."""

    status_code = 503
    code = "vision_unavailable"


class VisionResponseError(AppError):
    """The vision model answered, but not with a usable assessment."""

    status_code = 502
    code = "vision_bad_response"


class InvalidImageError(AppError):
    status_code = 422
    code = "invalid_image"


class UnsupportedImageTypeError(AppError):
    status_code = 415
    code = "unsupported_image_type"


class ImageTooLargeError(AppError):
    status_code = 413
    code = "image_too_large"
