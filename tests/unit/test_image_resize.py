"""Unit tests for the resize_image function in llm_service."""

import io

import pytest
from PIL import Image

from server.config import ImageResizeSettings
from server.services.llm_service import resize_image


def _make_png(width: int, height: int) -> bytes:
    """Create a minimal in-memory PNG of the given size."""
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _image_size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


class TestResizeModeNone:
    def test_returns_original_bytes(self):
        original = _make_png(3000, 2000)
        result = resize_image(original, "png", ImageResizeSettings(mode="none"))
        assert result == original


class TestResizeModeAuto:
    def test_no_resize_when_within_limit(self):
        original = _make_png(1000, 800)
        result = resize_image(original, "png", ImageResizeSettings(mode="auto", max_px=1536))
        w, h = _image_size(result)
        assert w == 1000 and h == 800

    def test_resizes_when_exceeds_limit(self):
        original = _make_png(3000, 2000)
        result = resize_image(original, "png", ImageResizeSettings(mode="auto", max_px=1536))
        w, h = _image_size(result)
        assert max(w, h) == 1536

    def test_aspect_ratio_preserved(self):
        original = _make_png(3000, 1500)  # 2:1 ratio
        result = resize_image(original, "png", ImageResizeSettings(mode="auto", max_px=1000))
        w, h = _image_size(result)
        assert w == 1000
        assert h == 500

    def test_portrait_image(self):
        original = _make_png(1000, 3000)  # portrait
        result = resize_image(original, "png", ImageResizeSettings(mode="auto", max_px=1000))
        w, h = _image_size(result)
        assert h == 1000
        assert w == 333


class TestResizeModeFixed:
    def test_always_resizes_even_small_image(self):
        original = _make_png(500, 400)
        result = resize_image(original, "png", ImageResizeSettings(mode="fixed", max_px=1536))
        w, h = _image_size(result)
        assert max(w, h) == 1536

    def test_resizes_large_image(self):
        original = _make_png(4000, 3000)
        result = resize_image(original, "png", ImageResizeSettings(mode="fixed", max_px=2048))
        w, h = _image_size(result)
        assert max(w, h) == 2048


class TestResizeJpegQuality:
    def test_lower_quality_produces_smaller_file(self):
        # Use a large image with varied content so quality difference is visible
        import random
        img = Image.new("RGB", (2000, 1500))
        pixels = [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                  for _ in range(2000 * 1500)]
        img.putdata(pixels)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        original = buf.getvalue()

        high_q = resize_image(original, "jpeg", ImageResizeSettings(mode="fixed", max_px=800, quality=95))
        low_q = resize_image(original, "jpeg", ImageResizeSettings(mode="fixed", max_px=800, quality=20))
        assert len(low_q) < len(high_q)


class TestImageResizeSettingsDefaults:
    def test_default_mode_is_auto(self):
        s = ImageResizeSettings()
        assert s.mode == "auto"

    def test_default_max_px(self):
        assert ImageResizeSettings().max_px == 1536

    def test_default_quality(self):
        assert ImageResizeSettings().quality == 80
