"""Unit tests for server.services.image_validator module."""

import pytest

from server.services.image_validator import ImageValidator


# ---------------------------------------------------------------------------
# Helper constants – minimal valid file headers
# ---------------------------------------------------------------------------
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 100


class TestImageValidatorFormat:
    """Tests for file-format validation (extension + magic bytes)."""

    def test_valid_png(self):
        result = ImageValidator.validate(PNG_HEADER, "screenshot.png")
        assert result.is_valid is True
        assert result.error_message == ""

    def test_valid_jpeg(self):
        result = ImageValidator.validate(JPEG_HEADER, "photo.jpeg")
        assert result.is_valid is True
        assert result.error_message == ""

    def test_valid_jpg(self):
        result = ImageValidator.validate(JPEG_HEADER, "photo.jpg")
        assert result.is_valid is True
        assert result.error_message == ""

    def test_uppercase_extension_png(self):
        result = ImageValidator.validate(PNG_HEADER, "image.PNG")
        assert result.is_valid is True

    def test_uppercase_extension_jpg(self):
        result = ImageValidator.validate(JPEG_HEADER, "image.JPG")
        assert result.is_valid is True

    def test_unsupported_format_bmp(self):
        result = ImageValidator.validate(b"BM" + b"\x00" * 50, "image.bmp")
        assert result.is_valid is False
        assert "Unsupported image format" in result.error_message

    def test_unsupported_format_gif(self):
        result = ImageValidator.validate(b"GIF89a" + b"\x00" * 50, "anim.gif")
        assert result.is_valid is False
        assert "Unsupported image format" in result.error_message

    def test_no_extension(self):
        result = ImageValidator.validate(PNG_HEADER, "noext")
        assert result.is_valid is False
        assert "Unsupported image format" in result.error_message

    def test_empty_extension(self):
        result = ImageValidator.validate(PNG_HEADER, "file.")
        assert result.is_valid is False

    def test_mismatched_magic_png_ext_jpeg_content(self):
        """Extension says PNG but content is JPEG."""
        result = ImageValidator.validate(JPEG_HEADER, "fake.png")
        assert result.is_valid is False
        assert "does not match" in result.error_message

    def test_mismatched_magic_jpeg_ext_png_content(self):
        """Extension says JPEG but content is PNG."""
        result = ImageValidator.validate(PNG_HEADER, "fake.jpeg")
        assert result.is_valid is False
        assert "does not match" in result.error_message

    def test_random_bytes_with_png_ext(self):
        result = ImageValidator.validate(b"\x00\x01\x02\x03", "random.png")
        assert result.is_valid is False
        assert "does not match" in result.error_message


class TestImageValidatorSize:
    """Tests for file-size validation."""

    def test_exactly_at_limit(self):
        """20 MB exactly should pass."""
        data = b"\x89PNG" + b"\x00" * (20 * 1024 * 1024 - 4)
        result = ImageValidator.validate(data, "big.png")
        assert result.is_valid is True

    def test_one_byte_over_limit(self):
        data = b"\x89PNG" + b"\x00" * (20 * 1024 * 1024 - 3)
        result = ImageValidator.validate(data, "toobig.png")
        assert result.is_valid is False
        assert "exceeds" in result.error_message

    def test_small_file(self):
        result = ImageValidator.validate(PNG_HEADER, "tiny.png")
        assert result.is_valid is True


class TestImageValidatorEdgeCases:
    """Edge-case and boundary tests."""

    def test_empty_bytes(self):
        """Empty content with valid extension should fail magic-byte check."""
        result = ImageValidator.validate(b"", "empty.png")
        assert result.is_valid is False

    def test_filename_with_multiple_dots(self):
        result = ImageValidator.validate(PNG_HEADER, "my.screen.shot.png")
        assert result.is_valid is True

    def test_mixed_case_extension(self):
        result = ImageValidator.validate(JPEG_HEADER, "photo.JpEg")
        assert result.is_valid is True
