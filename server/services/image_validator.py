"""Image validation module for the AI Alarm System.

Validates uploaded images by checking:
- File extension (must be PNG or JPEG)
- Magic bytes (file signature verification)
- File size (must not exceed 20MB)
"""

from server.models import ValidationResult


# Magic byte signatures for supported image formats
_PNG_MAGIC = b"\x89PNG"
_JPEG_MAGIC = b"\xff\xd8\xff"


class ImageValidator:
    """Validates image format and size before LLM analysis."""

    ALLOWED_FORMATS = {"png", "jpeg", "jpg"}
    MAX_SIZE_MB = 20

    @staticmethod
    def validate(image_bytes: bytes, filename: str) -> ValidationResult:
        """Validate image format (extension + magic bytes) and size.

        Args:
            image_bytes: Raw image file content.
            filename: Original filename including extension.

        Returns:
            ValidationResult with is_valid=True if the image passes all
            checks, otherwise is_valid=False with an error_message.
        """
        # 1. Check file extension
        ext = _extract_extension(filename)
        if ext not in ImageValidator.ALLOWED_FORMATS:
            return ValidationResult(
                is_valid=False,
                error_message=(
                    f"Unsupported image format '.{ext}'. "
                    "Only PNG and JPEG are allowed."
                ),
            )

        # 2. Check magic bytes match the declared extension
        if not _magic_bytes_match(image_bytes, ext):
            return ValidationResult(
                is_valid=False,
                error_message=(
                    "File content does not match the declared format. "
                    "The file may be corrupted or mislabeled."
                ),
            )

        # 3. Check file size
        max_bytes = ImageValidator.MAX_SIZE_MB * 1024 * 1024
        if len(image_bytes) > max_bytes:
            size_mb = len(image_bytes) / (1024 * 1024)
            return ValidationResult(
                is_valid=False,
                error_message=(
                    f"Image size {size_mb:.1f}MB exceeds the "
                    f"{ImageValidator.MAX_SIZE_MB}MB limit."
                ),
            )

        return ValidationResult(is_valid=True)


def _extract_extension(filename: str) -> str:
    """Extract and normalise the file extension (lowercase, no dot)."""
    dot_idx = filename.rfind(".")
    if dot_idx == -1 or dot_idx == len(filename) - 1:
        return ""
    return filename[dot_idx + 1 :].lower()


def _magic_bytes_match(data: bytes, ext: str) -> bool:
    """Return True if the leading bytes match the expected format."""
    if ext == "png":
        return data[:4] == _PNG_MAGIC
    if ext in ("jpeg", "jpg"):
        return data[:3] == _JPEG_MAGIC
    return False
