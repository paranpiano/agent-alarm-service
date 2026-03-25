"""LLM Service module for the AI Alarm System.

Analysis flow (when DI is configured):

  전체 이미지 (1920x1170)
          │
          ▼
    4개 패널 크롭 (1회, DI와 LLM이 공유)
    ┌──────────────────────────────────────┐
    │ top_left  top_right  bottom_left  bottom_right │
    └──────────────────────────────────────┘
          │                       │
          ▼ (병렬)                 ▼ (병렬)
    ┌──────────────┐       ┌──────────────┐
    │     DI       │       │     LLM      │
    │  S520 숫자   │       │  S520 색상   │
    │  S530 숫자   │       │  S530 색상   │
    │  S810 숫자   │       │  S540 색상   │
    │ (테이블 OCR) │       │  S810 색상   │
    └──────────────┘       └──────────────┘
          │                       │
          ▼                       ▼
    숫자 추출 결과           색상 감지 결과
    (NG if >= 3000)         (NG if RED 영역)
          │                       │
          └──────────┬────────────┘
                     ▼
               최종 판정 병합
               - 숫자 NG 항목 (DI)
               - 색상 NG 항목 (LLM)
               - 전체 status (OK/NG/UNKNOWN)
               - reasoning + log

DI 검증 실패 시 (장비 ID 누락 또는 값 개수 부족):
  - LLM 호출 없이 즉시 UNKNOWN 반환
  - 부분 추출 데이터를 equipment_data에 포함하여 로그 기록
  - 이메일 알림 발송 (SNS_ENABLED=true 시)

Fallback (DI 미설정 시):
  전체 이미지를 LLM 단일 호출로 분석 (기존 방식).
"""

import base64
import io
import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

import yaml
from langchain.schema import HumanMessage
from langchain_openai import AzureChatOpenAI
from PIL import Image

from server.config import AppConfig, ImageResizeSettings, PromptConfig
from server.models import JudgmentStatus, LLMResponse
from server.services.document_intelligence import (
    DocumentIntelligenceService,
    PanelExtractionResult,
    _crop_panel,
    _PANEL_CROPS,
)

logger = logging.getLogger(__name__)

_USES_MAX_COMPLETION_TOKENS = ("gpt-4.1", "gpt-5", "o1", "o3")

# Color detection prompt — image only, no numeric data
_COLOR_DETECTION_PROMPT = """You are a visual inspector analyzing an HMI panel image for alarm conditions.

Your ONLY task is to detect RED background areas in this panel image.

Instructions:
1. First, identify the equipment from the title bar (S520, S530, S540, or S810).

2. For S540 panels ONLY — check the screen mode:
   - NORMAL mode: shows a 3D layout with station labels (1-1, 1-2, 2-1 ... 6-2) and numeric counts.
   - WRONG mode: shows any other screen such as "Setup & Parameters", "Machine Parameter",
     "BypassMES", "BypassCamera", "BypassScanner", "DripBypass", or any menu/settings page.
   If the S540 panel is NOT showing the normal 3D station layout, set:
     "wrong_screen": true, "ng": false
   This will be treated as UNKNOWN by the system.

3. Scan the entire image for any areas with a RED or bright-red background color.
   Normal background colors are: black, dark gray, cyan/blue (table rows), white, green.
   ALARM color is: RED (any shade of red background on a label, button, or station).

4. IMPORTANT — Ignore the following UI elements (these are NOT alarms):
   - A yellow/bright-yellow rectangle with a red exclamation mark (!) inside it,
     located in the top-left corner of the panel near the title bar.
     This is a standard HMI notification icon, NOT an equipment alarm.

5. For each red area found (excluding the above):
   - Describe its location in the panel (e.g. center, table row, station label)
   - Read ALL text visible inside or near that red area
   - Explain why you consider it an alarm condition

6. If NO red areas are found (or only the ignored notification icon), state that clearly.

Respond with ONLY a valid JSON object:
{
  "equipment_id": "S520 or S530 or S540 or S810 (read from title bar)",
  "wrong_screen": false,
  "red_areas_found": true or false,
  "red_areas": [
    {
      "location": "description of where in the panel",
      "text": "all text visible in/near the red area",
      "reasoning": "why this is considered an alarm"
    }
  ],
  "overall_reasoning": "step-by-step explanation of your visual inspection",
  "ng": true or false
}

CRITICAL: Start with { and end with }. No markdown.
"""


# Expected value counts per equipment field (for DI validation)
# Allow up to 2 missing values per field to tolerate OCR key-parsing errors
# (e.g. '8A' misread instead of '8#' causes one key to be skipped)
_EXPECTED_FIELD_COUNTS: dict[str, dict[str, int]] = {
    "S520": {"curing_oven": 14, "preheating_oven": 14},
    "S530": {"cooling_1_line": 14, "cooling_2_line": 14},
    "S810": {"cooling_1_line": 15, "cooling_2_line": 15},
}
_FIELD_COUNT_TOLERANCE = 2  # allow up to 2 missing values before flagging UNKNOWN


def _validate_di_result(di_result: Any) -> tuple[bool, str]:
    """Validate DI extraction result.

    Checks that all expected equipment IDs are identified and each field
    has enough numeric values extracted from the WHITE row.
    """
    if di_result is None:
        return False, "DI 추출 결과가 없습니다. 이미지 캡처 화면에 문제가 있을 수 있습니다."

    panels_by_eq: dict[str, Any] = {
        panel.equipment_id: panel
        for panel in di_result.panels.values()
        if panel.equipment_id and panel.equipment_id != "S540"
    }

    missing_eqs = [eq for eq in ("S520", "S530", "S810") if eq not in panels_by_eq]
    if missing_eqs:
        extracted_summary = {
            eq: [
                f"{table.infer_field_name(eq) or 'unknown'}: {len(table.white_row_values())}값"
                for table in panel.tables if table.white_row_values()
            ]
            for eq, panel in panels_by_eq.items()
        }
        logger.warning(
            "DI validation failed — missing equipment: %s | extracted: %s",
            missing_eqs, extracted_summary,
        )
        return False, (
            f"장비 패널을 식별할 수 없습니다: {', '.join(missing_eqs)}. "
            "화면이 가려지거나 조작되었을 가능성이 있습니다."
        )

    for eq_id, expected_fields in _EXPECTED_FIELD_COUNTS.items():
        panel = panels_by_eq[eq_id]
        # Collect all numeric values across all data tables for this equipment
        all_values: list[int] = []
        for table in panel.tables:
            vals = table.white_row_values()
            if vals:
                all_values.extend(vals)

        total_expected = sum(expected_fields.values())
        if len(all_values) < total_expected - _FIELD_COUNT_TOLERANCE:
            logger.warning(
                "DI validation failed — %s: expected ~%d total values, got %d",
                eq_id, total_expected, len(all_values),
            )
            return False, (
                f"{eq_id} 값이 부족합니다 "
                f"(기대: ~{total_expected}개, 추출: {len(all_values)}개). "
                "화면이 가려지거나 조작되었을 가능성이 있습니다."
            )

    return True, ""


def _build_partial_equipment_data(di_result: Any | None) -> dict[str, Any]:
    """Build equipment_data from whatever DI managed to extract."""
    result: dict[str, Any] = {}
    if di_result is None:
        for eq_id in ("S520", "S530", "S540", "S810"):
            result[eq_id] = {"identified": False, "values": [], "ng_items": []}
        return result

    panels_by_eq: dict[str, Any] = {
        panel.equipment_id: panel
        for panel in di_result.panels.values()
        if panel.equipment_id
    }

    for eq_id in ("S520", "S530", "S540", "S810"):
        panel = panels_by_eq.get(eq_id)
        if panel is None:
            result[eq_id] = {"identified": False, "values": [], "ng_items": []}
            continue

        all_values: list[int] = []
        for table in panel.tables:
            all_values.extend(table.white_row_values())

        result[eq_id] = {
            "identified": True,
            "value_count": len(all_values),
            "ng_items": [],
        }

    return result


def _uses_completion_tokens(model_name: str) -> bool:
    name = model_name.lower()
    return any(name.startswith(p) or p in name for p in _USES_MAX_COMPLETION_TOKENS)


def get_azure_vision_llm(config: AppConfig) -> AzureChatOpenAI:
    model = config.vision_model
    token_kwargs: dict = (
        {"max_completion_tokens": 4096}
        if _uses_completion_tokens(model)
        else {"max_tokens": 4096}
    )
    logger.info("LLM client: deployment=%s", model)
    return AzureChatOpenAI(
        azure_endpoint=config.azure_endpoint,
        api_key=config.azure_api_key,
        api_version=config.api_version,
        azure_deployment=model,
        timeout=config.server.llm_timeout_seconds,
        **token_kwargs,
    )


def resize_image(image_bytes: bytes, image_format: str, settings: ImageResizeSettings) -> bytes:
    if settings.mode == "none":
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        longest = max(w, h)
        needs_resize = (settings.mode == "fixed") or (
            settings.mode == "auto" and longest > settings.max_px
        )
        if not needs_resize:
            return image_bytes
        ratio = settings.max_px / longest
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        save_fmt = "JPEG" if image_format.lower() in ("jpg", "jpeg") else "PNG"
        save_kwargs: dict = {"format": save_fmt}
        if save_fmt == "JPEG":
            save_kwargs["quality"] = settings.quality
        img.save(buf, **save_kwargs)
        return buf.getvalue()
    except Exception:
        logger.warning("Image resize failed; using original bytes")
        return image_bytes


class LLMService:
    """Analyzes HMI panel images using parallel DI (numeric) + LLM (color) pipeline."""

    def __init__(self, app_config: AppConfig) -> None:
        self.config: PromptConfig = app_config.prompt
        self.timeout_seconds: int = app_config.server.llm_timeout_seconds
        self.image_resize = app_config.image_resize
        self.llm: AzureChatOpenAI = get_azure_vision_llm(app_config)

        di = app_config.document_intelligence
        if di.enabled:
            self.doc_intelligence: DocumentIntelligenceService | None = DocumentIntelligenceService(
                endpoint=di.endpoint,
                api_key=di.api_key,
            )
            logger.info("Document Intelligence enabled — using DI+LLM pipeline")
        else:
            self.doc_intelligence = None
            logger.info("Document Intelligence not configured — using vision-only fallback")

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze_image(self, image_bytes: bytes, image_format: str) -> tuple[LLMResponse, int]:
        start_time = time.monotonic()
        image_bytes = resize_image(image_bytes, image_format, self.image_resize)

        if self.doc_intelligence and self.doc_intelligence.available:
            return self._analyze_di_plus_llm(image_bytes, start_time)
        else:
            return self._analyze_vision_only(image_bytes, image_format, start_time)

    # ── DI + LLM parallel pipeline ────────────────────────────────────────────

    def _analyze_di_plus_llm(
        self, image_bytes: bytes, start_time: float
    ) -> tuple[LLMResponse, int]:
        """
        1. Crop 4 panels (once)
        2. DI  : extract numeric data for S520/S530/S810 (parallel, 4 calls)
        3. LLM : detect red areas in all 4 panels (parallel, 4 calls)
        4. Merge numeric NG + color NG → final judgment
        """
        # Step 1: crop panels once, shared by DI and LLM
        panel_crops: dict[str, bytes] = {}
        for pos, fractions in _PANEL_CROPS.items():
            try:
                panel_crops[pos] = _crop_panel(image_bytes, fractions)
            except Exception as exc:
                logger.error("Crop failed for %s: %s", pos, exc)

        # Step 2 & 3: run DI and LLM concurrently
        # DI uses 4 workers for its panels; LLM uses 4 workers for color detection
        # Both run in the same executor pool simultaneously
        di_future: Future | None = None
        color_futures: dict[Future, str] = {}

        with ThreadPoolExecutor(max_workers=9) as executor:
            # Submit DI job (internally parallel across 4 panels)
            di_future = executor.submit(
                self.doc_intelligence.extract, image_bytes
            )

            # Submit LLM color detection for each panel
            for pos, panel_bytes in panel_crops.items():
                f = executor.submit(self._detect_color, pos, panel_bytes)
                color_futures[f] = pos

            # Collect DI result
            di_result = None
            try:
                di_result = di_future.result()
                logger.info("DI extraction complete")
            except Exception as exc:
                logger.warning("DI failed: %s", exc)

            # Validate DI result before proceeding
            is_valid, invalid_reason = _validate_di_result(di_result)
            if not is_valid:
                logger.warning("DI validation failed: %s", invalid_reason)
                # Cancel pending LLM futures (best effort)
                for f in color_futures:
                    f.cancel()
                # Build partial equipment_data from whatever DI did extract
                partial_data = _build_partial_equipment_data(di_result)
                logger.warning(
                    "Partial DI extraction data: %s",
                    json.dumps(partial_data, ensure_ascii=False),
                )
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return LLMResponse(
                    status=JudgmentStatus.UNKNOWN,
                    reason=invalid_reason,
                    raw_response="",
                    equipment_data=partial_data,
                ), elapsed_ms

            # Collect LLM color results
            color_results: dict[str, dict] = {}
            for future in as_completed(color_futures):
                pos = color_futures[future]
                try:
                    color_results[pos] = future.result()
                except Exception as exc:
                    logger.error("Color detection failed for %s: %s", pos, exc)
                    color_results[pos] = {}

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Step 4: merge
        response = self._merge_results(di_result, color_results, panel_crops)
        return response, elapsed_ms

    def _detect_color(self, position: str, panel_bytes: bytes) -> dict:
        """Send one cropped panel to LLM for red area detection."""
        b64 = base64.b64encode(panel_bytes).decode("utf-8")
        messages = [HumanMessage(content=[
            {"type": "text", "text": _COLOR_DETECTION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ])]
        response = self.llm.invoke(messages)
        raw = self._strip_code_fences(response.content.strip())
        result = self._try_parse_json(raw) or {}
        eq = result.get("equipment_id", "?")
        ng = result.get("ng", False)
        red_count = len(result.get("red_areas", []))
        logger.info(
            "Color detection [%s/%s]: ng=%s, red_areas=%d",
            position, eq, ng, red_count,
        )
        if ng:
            for area in result.get("red_areas", []):
                logger.warning(
                    "RED AREA [%s/%s] location=%s text=%s | reasoning=%s",
                    position, eq,
                    area.get("location", ""),
                    area.get("text", ""),
                    area.get("reasoning", ""),
                )
        return result

    def _merge_results(
        self,
        di_result: Any | None,
        color_results: dict[str, dict],
        panel_crops: dict[str, bytes],
    ) -> LLMResponse:
        """Merge DI numeric results and LLM color results into one LLMResponse.

        - S520/S530/S810: numeric data from DI, color NG from LLM
        - S540: color/station data from LLM only (no DI numeric data)
        - Final equipment_data is assembled here — LLM is NOT asked to return numeric fields
        """
        # Build position → equipment map: DI가 우선, LLM 색상 결과로 보완
        pos_to_eq: dict[str, str] = {}
        # 1. DI 결과 우선 (더 신뢰도 높음)
        if di_result:
            for pos, panel in di_result.panels.items():
                if panel.equipment_id:
                    pos_to_eq[pos] = panel.equipment_id
        # 2. LLM 색상 결과로 보완 (DI에서 못 찾은 경우)
        for pos, r in color_results.items():
            if r.get("equipment_id") and pos not in pos_to_eq:
                pos_to_eq[pos] = r["equipment_id"]

        # Normalize color result equipment_ids to canonical IDs (S520/S530/S540/S810)
        # LLM may return e.g. "S540-Robot-2" instead of "S540"
        _CANONICAL_IDS = ("S520", "S530", "S540", "S810")
        def _normalize_eq_id(raw: str) -> str:
            for cid in _CANONICAL_IDS:
                if cid in raw:
                    return cid
            return raw

        # Normalize pos_to_eq
        pos_to_eq = {pos: _normalize_eq_id(eq) for pos, eq in pos_to_eq.items()}

        # Build normalized color_results keyed by canonical equipment_id
        color_by_eq: dict[str, dict] = {}
        for pos, r in color_results.items():
            raw_eq = r.get("equipment_id", "")
            canon_eq = _normalize_eq_id(raw_eq)
            if canon_eq:
                color_by_eq[canon_eq] = r

        equipment_data: dict[str, Any] = {}
        all_ng_items: list[str] = []

        for eq_id in ("S520", "S530", "S540", "S810"):
            eq_entry: dict[str, Any] = {"identified": True, "ng_items": []}
            ng_items: list[str] = []

            # ── Numeric data + NG from DI (S520/S530/S810) ───────────────────
            if eq_id != "S540" and di_result:
                for pos, panel in di_result.panels.items():
                    if panel.equipment_id != eq_id:
                        continue
                    all_values: list[int] = []
                    for table in panel.tables:
                        vals = table.white_row_values()
                        all_values.extend(vals)
                        # Store by field name for response
                        field_name = table.infer_field_name(eq_id)
                        if field_name and field_name not in eq_entry:
                            eq_entry[field_name] = vals

                    # Check >= 3000
                    for val in all_values:
                        if val >= 3000:
                            item = f"value {val} (>= 3000)"
                            ng_items.append(item)
                            logger.warning("Numeric NG [%s] %s", eq_id, item)

            # ── Color NG from LLM (all equipment) ────────────────────────────
            color_data = color_by_eq.get(eq_id, {})
            if color_data:
                # S540 wrong screen → UNKNOWN
                if eq_id == "S540" and color_data.get("wrong_screen"):
                    logger.warning(
                        "S540 wrong screen detected: %s",
                        color_data.get("overall_reasoning", ""),
                    )
                    elapsed_ms = 0  # will be set by caller
                    # Signal UNKNOWN via a special ng_item
                    ng_items.append("WRONG_SCREEN: S540이 정상 화면(3D 스테이션 레이아웃)을 표시하지 않습니다.")

                # S540: store station data from LLM response
                if eq_id == "S540":
                    stations = color_data.get("stations")
                    if stations:
                        eq_entry["stations"] = stations

                if color_data.get("ng"):
                    for area in color_data.get("red_areas", []):
                        item = f"RED [{area.get('location', '')}]: {area.get('text', '')}"
                        ng_items.append(item)

                reasoning = color_data.get("overall_reasoning", "")
                if reasoning:
                    eq_entry["color_reasoning"] = reasoning

            eq_entry["ng_items"] = ng_items
            equipment_data[eq_id] = eq_entry
            if ng_items:
                all_ng_items.extend(f"{eq_id}: {item}" for item in ng_items)

        # Check if any equipment was not identified
        identified_eqs = set(pos_to_eq.values())
        missing = [eq for eq in ("S520", "S530", "S540", "S810") if eq not in identified_eqs]

        # Check for S540 wrong screen
        wrong_screen = any(
            "WRONG_SCREEN" in item
            for item in equipment_data.get("S540", {}).get("ng_items", [])
        )

        if missing:
            logger.warning("Unidentified panels: %s", missing)
            status = JudgmentStatus.UNKNOWN
            reason = f"패널 식별 불가: {', '.join(missing)}"
        elif wrong_screen:
            status = JudgmentStatus.UNKNOWN
            reason = "S540 패널이 정상 화면(3D 스테이션 레이아웃)을 표시하지 않습니다. 화면이 다른 메뉴로 전환되어 있습니다."
            # Clear the wrong_screen marker from ng_items
            s540_data = equipment_data.get("S540", {})
            s540_data["ng_items"] = [
                i for i in s540_data.get("ng_items", []) if "WRONG_SCREEN" not in i
            ]
        elif all_ng_items:
            status = JudgmentStatus.NG
            reason = "NG 항목 발견: " + "; ".join(all_ng_items)
        else:
            status = JudgmentStatus.OK
            reason = "모든 장비 정상입니다."

        return LLMResponse(
            status=status,
            reason=reason,
            equipment_data=equipment_data,
        )

    # ── Vision-only fallback ──────────────────────────────────────────────────

    def _analyze_vision_only(
        self, image_bytes: bytes, image_format: str, start_time: float
    ) -> tuple[LLMResponse, int]:
        """Single full-image LLM call (fallback when DI unavailable)."""
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = f"image/{image_format}"
        prompt_text = self._build_full_prompt()
        messages = [HumanMessage(content=[
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_image}"}},
        ])]
        try:
            response = self.llm.invoke(messages)
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return self._parse_response(response.content), elapsed_ms
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            if elapsed_ms >= self.timeout_seconds * 1000 or isinstance(exc, TimeoutError):
                return LLMResponse(
                    status=JudgmentStatus.TIMEOUT,
                    reason=f"LLM timeout ({self.timeout_seconds}s)",
                    raw_response="",
                ), elapsed_ms
            raise

    def _build_full_prompt(self) -> str:
        parts: list[str] = [self.config.system_prompt.strip(), ""]
        parts.append("=== Equipment Definitions ===")
        parts.append(yaml.dump(
            self.config.equipment_definitions,
            allow_unicode=True, default_flow_style=False,
        ).strip())
        parts.append("")
        parts.append("=== Judgment Criteria ===")
        for step_name, step_content in self.config.judgment_criteria.items():
            parts.append(f"[{step_name}]")
            parts.append(str(step_content).strip())
            parts.append("")
        parts.append("=== Response Format ===")
        parts.append(yaml.dump(
            self.config.response_format,
            allow_unicode=True, default_flow_style=False,
        ).strip())
        parts.append("")
        parts.append("CRITICAL: Respond with ONLY a valid JSON object. Start with { and end with }.")
        return "\n".join(parts)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_response(self, raw_response: str) -> LLMResponse:
        cleaned = raw_response.strip()
        data = self._try_parse_json(cleaned)
        if data is None:
            data = self._try_parse_json(self._strip_code_fences(cleaned))
        if data is None:
            first, last = cleaned.find("{"), cleaned.rfind("}")
            if first != -1 and last > first:
                data = self._try_parse_json(cleaned[first:last + 1])
        if data is None:
            return LLMResponse(
                status=JudgmentStatus.UNKNOWN,
                reason="Failed to parse LLM response",
                raw_response=raw_response,
            )
        raw_status = str(data.get("status", "UNKNOWN")).upper().strip()
        try:
            status = JudgmentStatus(raw_status)
        except ValueError:
            status = JudgmentStatus.UNKNOWN
        return LLMResponse(
            status=status,
            reason=str(data.get("reason", "")),
            raw_response=raw_response,
            equipment_data=data.get("equipment_data"),
        )

    @staticmethod
    def _try_parse_json(text: str) -> dict[str, Any] | None:
        try:
            result = json.loads(text)
            return result if isinstance(result, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        if text.startswith("```"):
            lines = text.split("\n")
            end = -1 if lines[-1].strip() == "```" else len(lines)
            return "\n".join(lines[1:end]).strip()
        return text
