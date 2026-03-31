"""Flask API routes for the AI Alarm System.

Provides:
- POST /api/v1/analyze: Accept multipart/form-data image, validate, analyze via LLM, return result.
- GET /api/v1/health: Server health check endpoint.

Error codes: INVALID_IMAGE_FORMAT, IMAGE_TOO_LARGE, LLM_SERVICE_ERROR, MISSING_IMAGE.
"""

import io
import logging
import random
import time
from datetime import datetime

from flask import Blueprint, Response, current_app, jsonify, request
from PIL import Image

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
_cloud_logger = None  # type: ignore[assignment]


def init_routes(
    llm_service: LLMService,
    result_storage=None,
    judgment_logger=None,
    email_notifier=None,
    cloud_logger=None,
) -> None:
    global _llm_service, _result_storage, _judgment_logger, _email_notifier, _cloud_logger  # noqa: PLW0603
    _llm_service = llm_service
    _result_storage = result_storage
    _judgment_logger = judgment_logger
    _email_notifier = email_notifier
    _cloud_logger = cloud_logger


def _generate_request_id() -> str:
    """Generate a unique request ID in the format req_YYYYMMDD_HHMMSS_XXXX."""
    now = datetime.now()
    suffix = f"{random.randint(0, 9999):04d}"
    return f"req_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"


def _is_single_panel_image(image_bytes: bytes) -> bool:
    """Detect whether the image is a single panel (not a 4-panel composite).

    Full 4-panel HMI images are 1920x1170 (~2.25M px).
    Single panel crops are 960x585 (~0.56M px) — same aspect ratio, but 1/4 the area.
    Threshold: total pixels < 1,000,000 → single panel.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        is_single = (w * h) < 1_000_000
        logger.info("Auto panel detection: %dx%d (%d px) → %s", w, h, w * h, "single" if is_single else "4-panel")
        return is_single
    except Exception:
        return False


def _local_iso_timestamp() -> str:
    """Return the current local time as an ISO 8601 string."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


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
            "timestamp": _local_iso_timestamp(),
        }
    }
    return jsonify(body), http_status


@api_bp.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    """GET /api/v1/health — server health check."""
    return jsonify({"status": "healthy", "timestamp": _local_iso_timestamp()}), 200


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

    # single_panel mode: image is already a cropped panel (no 4-way split needed)
    # "auto" (default): detect automatically from image aspect ratio
    # "single_panel": force single panel mode
    # anything else: force 4-panel mode
    mode = request.form.get("mode", "auto").lower()
    if mode == "single_panel":
        single_panel = True
    elif mode == "auto":
        single_panel = _is_single_panel_image(image_bytes)
        logger.info("Auto single_panel detection: %s (mode=auto)", single_panel)
    else:
        single_panel = False

    # 4. Call LLM analysis
    try:
        llm_response, processing_time_ms = _llm_service.analyze_image(
            image_bytes, image_format, single_panel=single_panel
        )
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
        timestamp=_local_iso_timestamp(),
        processing_time_ms=processing_time_ms,
        image_name=filename,
        equipment_data=llm_response.equipment_data,
    )

    debug_mode = current_app.debug

    # 6. Persist result and log judgment (debug mode only for file storage)
    if _judgment_logger is not None:
        try:
            _judgment_logger.log_judgment(result)
        except Exception:
            logger.exception("Failed to log judgment for request_id=%s", request_id)

    # Cloud log upload (always, async fire-and-forget)
    if _cloud_logger is not None:
        _cloud_logger.log_async(result)

    if debug_mode and _result_storage is not None:
        try:
            _result_storage.save_result(result)
            if result.status == JudgmentStatus.UNKNOWN:
                _result_storage.save_unknown_image(request_id, image_bytes, filename)
        except Exception:
            logger.exception("Failed to persist result for request_id=%s", request_id)

    # 7. Send email alert for UNKNOWN status
    if _email_notifier is not None and result.status == JudgmentStatus.UNKNOWN:
        try:
            if result.equipment_data:
                logger.warning(
                    "UNKNOWN status equipment_data for request_id=%s: %s",
                    request_id,
                    result.equipment_data,
                )
            _email_notifier.send_alert(result)
        except Exception:
            logger.exception("Failed to send email alert for request_id=%s", request_id)

    return jsonify(result.to_dict()), 200
