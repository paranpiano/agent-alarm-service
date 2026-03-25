"""Integration accuracy test for the AI Alarm System.

Sends all test images to a running server and evaluates prediction accuracy.
Produces a JSON report at ``data/test_report.json``.

Run with::

    python -m pytest tests/integration/test_accuracy.py -v -s

Requires the server to be running at http://localhost:8000.
"""

import json
import time
from pathlib import Path

import pytest
import requests

_SERVER_URL = "http://localhost:8000"
_SLOW_THRESHOLD_MS = 15_000
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_TEST_IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "test_images"
_REPORT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "test_report.json"


def _server_available() -> bool:
    """Return True if the server health endpoint responds."""
    try:
        r = requests.get(f"{_SERVER_URL}/api/v1/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _collect_images() -> list[tuple[Path, str]]:
    """Collect (image_path, expected_label) pairs from test_images/."""
    images: list[tuple[Path, str]] = []
    if not _TEST_IMAGES_DIR.is_dir():
        return images
    for subfolder in sorted(_TEST_IMAGES_DIR.iterdir()):
        if not subfolder.is_dir():
            continue
        expected = subfolder.name.upper()
        for img in sorted(subfolder.iterdir()):
            if img.suffix.lower() in _IMAGE_EXTENSIONS:
                images.append((img, expected))
    return images


def _analyze_image(image_path: Path) -> dict:
    """Send a single image to the server and return the JSON response."""
    with open(image_path, "rb") as f:
        files = {"image": (image_path.name, f)}
        resp = requests.post(
            f"{_SERVER_URL}/api/v1/analyze",
            files=files,
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()


@pytest.mark.skipif(not _server_available(), reason="Server not available")
def test_accuracy() -> None:
    """Send every test image to the server and report accuracy."""
    images = _collect_images()
    if not images:
        pytest.skip("No test images found")

    results: list[dict] = []
    correct = 0
    total = len(images)
    total_time_ms = 0
    failures: list[dict] = []
    slow: list[dict] = []

    for img_path, expected in images:
        data = _analyze_image(img_path)
        actual = data.get("status", "UNKNOWN").upper()
        time_ms = data.get("processing_time_ms", 0)
        reason = data.get("reason", "")
        match = actual == expected
        if match:
            correct += 1
        else:
            failures.append({
                "image": img_path.name,
                "expected": expected,
                "actual": actual,
                "reason": reason,
            })
        if time_ms > _SLOW_THRESHOLD_MS:
            slow.append({"image": img_path.name, "time_ms": time_ms})
        total_time_ms += time_ms
        results.append({
            "image": img_path.name,
            "expected": expected,
            "actual": actual,
            "match": match,
            "time_ms": time_ms,
            "reason": reason,
        })

    accuracy = (correct / total * 100) if total else 0
    avg_time = (total_time_ms / total) if total else 0

    report = {
        "total_images": total,
        "correct": correct,
        "accuracy_pct": round(accuracy, 2),
        "avg_response_time_ms": round(avg_time, 2),
        "failures": failures,
        "slow_responses": slow,
        "results": results,
    }

    # Save report
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Total images : {total}")
    print(f"Correct      : {correct}")
    print(f"Accuracy     : {accuracy:.1f}%")
    print(f"Avg time     : {avg_time:.0f} ms")
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f_item in failures:
            print(f"  {f_item['image']}: expected={f_item['expected']}, "
                  f"actual={f_item['actual']}, reason={f_item['reason'][:80]}")
    if slow:
        print(f"\nSlow responses (>{_SLOW_THRESHOLD_MS}ms):")
        for s in slow:
            print(f"  {s['image']}: {s['time_ms']}ms")
    print(f"{'='*60}")
    print(f"Report saved to {_REPORT_PATH}")

    # Assertion so pytest reports pass/fail
    assert total > 0, "No images were tested"
