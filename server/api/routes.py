"""Flask API routes for the AI Alarm System.

Provides:
- POST /api/v1/analyze: Accept multipart/form-data image, validate, analyze via LLM, return result.
- GET /api/v1/health: Server health check endpoint.

Error codes: INVALID_IMAGE_FORMAT, IMAGE_TOO_LARGE, LLM_SERVICE_ERROR, MISSING_IMAGE.
"""

import logging
import time
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request

from server.models import JudgmentResult, JudgmentStatus
from server.services.image_validator import ImageValidator
from server.services.llm_service import LLMService

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

# Module-level references, set via init_routes().
_llm_service: LLMService | None = None
_result_storage = None  # type: ignore[assignment]
_judgment_logger = None  # type: ignore[assignment]
_email_notifier = None  # type: ignore[assignment]


def init_routes(
    llm_service: LLMService,
    result_storage=None,
    judgment_logger=None,
    email_notifier=None,
) -> None:
    """Inject service instances used by route handlers.

    Args:
        llm_service: Configured LLMService for image analysis.
        result_storage: Optional ResultStorage for persisting results.
        judgment_logger: Optional JudgmentLogger for logging judgments.
        email_notifier: Optional EmailNotifier for UNKNOWN status alerts.
    """
    global _llm_service, _result_storage, _judgment_logger, _email_notifier  # noqa: PLW0603
    _llm_service = llm_service
    _result_storage = result_storage
    _judgment_logger = judgment_logger
    _email_notifier = email_notifier


def _generate_request_id() -> str:
    """Generate a unique request ID in the format req_YYYYMMDD_HHMMSS_XXXX."""
    now = datetime.now(timezone.utc)
    import random
    suffix = f"{random.randint(0, 9999):04d}"
    return f"req_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"


def _utc_iso_timestamp() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error_response(code: str, message: str, request_id: str, http_status: int) -> tuple[Response, int]:
    """Build a standardised error JSON response.

    Args:
        code: Machine-readable error code (e.g. INVALID_IMAGE_FORMAT).
        message: Human-readable error description.
        request_id: The request identifier.
        http_status: HTTP status code to return.

    Returns:
        Tuple of (Flask Response, HTTP status code).
    """
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "timestamp": _utc_iso_timestamp(),
        }
    }
    return jsonify(body), http_status


@api_bp.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    """GET /api/v1/health — server health check."""
    return jsonify({"status": "healthy", "timestamp": _utc_iso_timestamp()}), 200


@api_bp.route("/analyze", methods=["POST"])
def analyze() -> tuple[Response, int]:
    """POST /api/v1/analyze — analyse an uploaded image.

    Expects multipart/form-data with:
      - image: The image file (PNG or JPEG).
      - request_id (optional): Client-supplied request identifier.

    Returns JSON with judgment result or an error envelope.
    """
    start_time = time.monotonic()

    # Resolve request_id
    request_id = request.form.get("request_id") or _generate_request_id()

    # 1. Check that an image file was provided
    if "image" not in request.files:
        return _error_response(
            code="MISSING_IMAGE",
            message="No image file provided. Include an 'image' field in multipart/form-data.",
            request_id=request_id,
            http_status=400,
        )

    file = request.files["image"]
    filename = file.filename or "unknown"
    image_bytes = file.read()

    # 2. Validate image format and size
    validation = ImageValidator.validate(image_bytes, filename)
    if not validation.is_valid:
        error_code = "IMAGE_TOO_LARGE" if "exceeds" in validation.error_message.lower() else "INVALID_IMAGE_FORMAT"
        return _error_response(
            code=error_code,
            message=validation.error_message,
            request_id=request_id,
            http_status=400,
        )

    # 3. Ensure LLM service is available
    if _llm_service is None:
        logger.error("LLM service not initialised")
        return _error_response(
            code="LLM_SERVICE_ERROR",
            message="LLM service is not available.",
            request_id=request_id,
            http_status=500,
        )

    # Determine image format from filename extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    image_format = "jpeg" if ext in ("jpg", "jpeg") else "png"

    # 4. Call LLM analysis
    try:
        llm_response, processing_time_ms = _llm_service.analyze_image(image_bytes, image_format)
    except Exception as exc:
        processing_time_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("LLM service error: %s", exc)
        return _error_response(
            code="LLM_SERVICE_ERROR",
            message=f"LLM analysis failed: {exc}",
            request_id=request_id,
            http_status=500,
        )

    # 5. Build JudgmentResult
    result = JudgmentResult(
        request_id=request_id,
        status=llm_response.status,
        reason=llm_response.reason,
        timestamp=_utc_iso_timestamp(),
        processing_time_ms=processing_time_ms,
        image_name=filename,
        equipment_data=llm_response.equipment_data,
    )

    # 6. Persist result and log judgment
    if _result_storage is not None:
        try:
            _result_storage.save_result(result)
            if result.status == JudgmentStatus.UNKNOWN:
                _result_storage.save_unknown_image(request_id, image_bytes, filename)
        except Exception:
            logger.exception("Failed to persist result for request_id=%s", request_id)

    if _judgment_logger is not None:
        try:
            _judgment_logger.log_judgment(result)
        except Exception:
            logger.exception("Failed to log judgment for request_id=%s", request_id)

    # 7. Send email alert for UNKNOWN status
    if _email_notifier is not None and result.status == JudgmentStatus.UNKNOWN:
        try:
            _email_notifier.send_alert(result)
        except Exception:
            logger.exception("Failed to send email alert for request_id=%s", request_id)

    return jsonify(result.to_dict()), 200
