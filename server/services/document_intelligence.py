"""Azure Document Intelligence service for extracting text and tables from images.

역할:
  전체 HMI 이미지를 4개 패널(2x2 그리드)로 크롭한 후, 각 패널을 병렬로 DI에 전송하여
  테이블 숫자 데이터를 추출합니다. S520/S530/S810의 WHITE row 값을 헤더 키 기반으로
  정확히 매핑하여 반환합니다. S540은 숫자 테이블이 없으므로 DI 추출 대상에서 제외됩니다.

패널 크롭 위치:
  top_left     → S520 (Preheating & Curing)
  top_right    → S530 (Cooling)
  bottom_left  → S540 (Robot)
  bottom_right → S810 (Housing Cooling)

필드 추론 방식 (infer_field_name):
  헤더 키 범위와 첫 번째 헤더 키를 기반으로 필드명을 결정합니다.
  sub_label(bounding region y좌표 기반 레이블)을 보조로 사용합니다.
  - S520: max_key <= 14 → curing_oven, min_key >= 14 → preheating_oven
  - S530: first_key == 1 → cooling_1_line, first_key == 14 → cooling_2_line
  - S810: sub_label에 '1' 포함 → cooling_1_line, '2' 포함 → cooling_2_line
"""

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 2x2 grid positions → (left, upper, right, lower) as fractions of (width, height)
_PANEL_CROPS = {
    "top_left":     (0.0, 0.0, 0.5, 0.5),
    "top_right":    (0.5, 0.0, 1.0, 0.5),
    "bottom_left":  (0.0, 0.5, 0.5, 1.0),
    "bottom_right": (0.5, 0.5, 1.0, 1.0),
}

_EQUIPMENT_IDS = ["S520", "S530", "S540", "S510", "S310", "S810"]


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ExtractedTable:
    """A single table extracted from one panel."""
    row_count: int
    col_count: int
    cells: list[dict[str, Any]] = field(default_factory=list)
    sub_label: str = ""  # e.g. 'Cooling 1 line', 'Curing Oven'

    def mapped_white_row(self) -> dict[str, str]:
        """Return white row values as {col_index: value} — kept for compatibility."""
        if self.row_count < 3:
            return {}
        white_cells = sorted(
            [c for c in self.cells if c["row"] == 2],
            key=lambda c: c["col"],
        )
        return {
            str(i): c["content"].strip()
            for i, c in enumerate(white_cells)
            if _is_numeric(c["content"].strip())
        }

    def white_row_values(self) -> list[int]:
        """Return all numeric values from the WHITE row (row index 2) as a plain list."""
        if self.row_count < 3:
            return []
        return [
            int(float(c["content"].replace(",", "").replace(" ", "").strip()))
            for c in self.cells
            if c["row"] == 2 and _is_numeric(c["content"].strip())
        ]

    def header_keys(self) -> list[int]:
        """Return sorted list of numeric header keys found in row 0."""
        keys = []
        for c in self.cells:
            if c["row"] == 0:
                k = _parse_header_key(c["content"])
                if k is not None:
                    keys.append(int(k))
        return sorted(keys)

    def infer_field_name(self, equipment_id: str) -> str:
        """Kept for compatibility — field assignment is now done by table index in _merge_results."""
        return _normalize_field_name(self.sub_label) or ""


@dataclass
class PanelExtractionResult:
    """OCR result for a single cropped panel.

    Attributes:
        equipment_id: Detected equipment label (e.g. 'S520'), or '' if unknown.
        tables: Tables extracted from this panel.
    """
    equipment_id: str = ""
    tables: list[ExtractedTable] = field(default_factory=list)

    def to_prompt_context(self) -> str:
        """Return a formatted string of mapped table data for LLM injection."""
        parts: list[str] = []
        eq = self.equipment_id or "UNKNOWN"
        data_tables = [t for t in self.tables if t.mapped_white_row()]
        if not data_tables:
            return ""
        for i, table in enumerate(data_tables):
            mapped = table.mapped_white_row()
            field_name = table.infer_field_name(eq) or table.sub_label or f"Table {i + 1}"
            parts.append(
                f"[{eq} {field_name}] WHITE row mapped values: "
                + json.dumps(mapped, ensure_ascii=False)
            )
        return "\n".join(parts)


@dataclass
class DocumentExtractionResult:
    """Aggregated OCR result for all 4 panels.

    Attributes:
        panels: Dict of position → PanelExtractionResult.
    """
    panels: dict[str, PanelExtractionResult] = field(default_factory=dict)

    def to_prompt_context(self) -> str:
        """Return combined prompt context for all panels."""
        parts = [
            "=== Pre-Extracted Table Data (OCR, per panel) ===",
            "Each entry is a fully mapped {key: value} dict from the WHITE row.",
            "Use these values AS-IS for the corresponding equipment field.",
            "",
        ]
        for pos in ("top_left", "top_right", "bottom_left", "bottom_right"):
            panel = self.panels.get(pos)
            if panel:
                ctx = panel.to_prompt_context()
                if ctx:
                    parts.append(ctx)
        parts.append("")
        return "\n".join(parts)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_numeric(value: str) -> bool:
    try:
        float(value.replace(",", "").replace(" ", "").strip())
        return True
    except ValueError:
        return False


def _parse_header_key(header: str) -> str | None:
    """Extract numeric key from '1#', '14#', '15#' etc. Returns None if not valid."""
    h = header.replace("#", "").strip()
    return h if h.isdigit() else None


def _normalize_field_name(label: str | None) -> str:
    """Normalize a DI sub_label to a canonical field name.

    Maps human-readable labels (case-insensitive) to snake_case field names:
      'Curing Oven'      → 'curing_oven'
      'Preheating Oven'  → 'preheating_oven'
      'Cooling 1 line'   → 'cooling_1_line'
      'Cooling 2 line'   → 'cooling_2_line'
      'Cooling 1 Line'   → 'cooling_1_line'
      'Cooling 2 Line'   → 'cooling_2_line'
    Returns empty string if no match.
    """
    if not label:
        return ""
    low = label.lower().strip()
    if "curing" in low:
        return "curing_oven"
    if "preheat" in low:
        return "preheating_oven"
    if "cooling" in low and "1" in low:
        return "cooling_1_line"
    if "cooling" in low and "2" in low:
        return "cooling_2_line"
    return ""


def _detect_equipment(paragraphs: list[str]) -> str:
    """Return the first equipment ID found in paragraph text, or ''."""
    text = "\n".join(paragraphs)
    for eq in _EQUIPMENT_IDS:
        if eq in text:
            return eq
    return ""


def _crop_panel(image_bytes: bytes, fractions: tuple[float, float, float, float]) -> bytes:
    """Crop image_bytes to the given fractional bounding box, return PNG bytes."""
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    lf, uf, rf, bf = fractions
    box = (int(w * lf), int(h * uf), int(w * rf), int(h * bf))
    cropped = img.crop(box)
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def _parse_di_result(result: Any) -> PanelExtractionResult:
    """Parse a DI AnalyzeResult into a PanelExtractionResult.

    Assigns a sub_label to each table by finding the nearest preceding
    label paragraph ('Cooling 1 line', 'Curing Oven', etc.) in reading order,
    using bounding region y-coordinates for accurate ordering.
    """
    paragraphs = [p.content for p in result.paragraphs] if result.paragraphs else []
    equipment_id = _detect_equipment(paragraphs)

    table_label_patterns = [
        "Cooling 2 line", "Cooling 1 line",
        "Curing Oven", "Preheating Oven",
        "Cooling 1 Line", "Cooling 2 Line",
    ]

    # Build list of (y, label) for label paragraphs using bounding regions
    label_y_list: list[tuple[float, str]] = []
    if result.paragraphs:
        for p_obj in result.paragraphs:
            for pattern in table_label_patterns:
                if pattern.lower() in p_obj.content.lower():
                    y = 0.0
                    try:
                        if p_obj.bounding_regions and p_obj.bounding_regions[0].polygon:
                            y = p_obj.bounding_regions[0].polygon[0].y
                    except Exception:
                        pass
                    label_y_list.append((y, pattern))
                    break
    label_y_list.sort(key=lambda x: x[0])

    tables: list[ExtractedTable] = []
    if result.tables:
        for t in result.tables:
            cells = [
                {"row": c.row_index, "col": c.column_index, "content": c.content}
                for c in t.cells
            ]

            # Get table's top-left y coordinate
            t_y = 0.0
            try:
                if t.bounding_regions and t.bounding_regions[0].polygon:
                    t_y = t.bounding_regions[0].polygon[0].y
            except Exception:
                pass

            # Find the label with the largest y that is still <= table's y
            sub_label = ""
            best_y = -1.0
            for ly, lbl in label_y_list:
                if ly <= t_y and ly > best_y:
                    best_y = ly
                    sub_label = lbl

            tables.append(ExtractedTable(
                row_count=t.row_count,
                col_count=t.column_count,
                cells=cells,
                sub_label=sub_label,
            ))

    return PanelExtractionResult(equipment_id=equipment_id, tables=tables)


# ── Service ───────────────────────────────────────────────────────────────────

class DocumentIntelligenceService:
    """Extracts table data from HMI panel images using Azure Document Intelligence.

    Crops the image into 4 panels and sends each to DI in parallel threads,
    ensuring each table is correctly attributed to its equipment.
    """

    def __init__(self, endpoint: str, api_key: str) -> None:
        try:
            from azure.ai.formrecognizer import DocumentAnalysisClient
            from azure.core.credentials import AzureKeyCredential
            self._client = DocumentAnalysisClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(api_key),
            )
            self._available = True
            logger.info("DocumentIntelligenceService initialized: %s", endpoint)
        except ImportError:
            logger.warning("azure-ai-formrecognizer not installed. Document Intelligence disabled.")
            self._available = False
        except Exception as exc:
            logger.warning("DocumentIntelligenceService init failed: %s", exc)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _extract_panel(self, panel_bytes: bytes, position: str) -> tuple[str, PanelExtractionResult]:
        """Run DI on a single cropped panel. Returns (position, result)."""
        try:
            poller = self._client.begin_analyze_document("prebuilt-layout", panel_bytes)
            result = poller.result()
            panel_result = _parse_di_result(result)
            logger.debug(
                "Panel %s: equipment=%s, tables=%d",
                position, panel_result.equipment_id, len(panel_result.tables),
            )
            return position, panel_result
        except Exception as exc:
            logger.error("DI extraction failed for panel %s: %s", position, exc)
            return position, PanelExtractionResult()

    def extract(self, image_bytes: bytes, content_type: str = "image/png", single_panel: bool = False) -> DocumentExtractionResult:
        """Extract tables from image.

        Args:
            image_bytes: HMI screenshot bytes (PNG or JPEG).
            content_type: Unused — kept for API compatibility.
            single_panel: If True, send image as-is (no 4-way crop).

        Returns:
            DocumentExtractionResult with per-panel OCR data.
        """
        if not self._available:
            return DocumentExtractionResult()

        if single_panel:
            # Send image as-is — it's already a single panel
            _, panel_result = self._extract_panel(image_bytes, "top_left")
            return DocumentExtractionResult(panels={"top_left": panel_result})

        # Crop 4 panels
        panel_bytes: dict[str, bytes] = {}
        for pos, fractions in _PANEL_CROPS.items():
            try:
                panel_bytes[pos] = _crop_panel(image_bytes, fractions)
            except Exception as exc:
                logger.error("Failed to crop panel %s: %s", pos, exc)

        # Run DI in parallel
        panels: dict[str, PanelExtractionResult] = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._extract_panel, pb, pos): pos
                for pos, pb in panel_bytes.items()
            }
            for future in as_completed(futures):
                pos, panel_result = future.result()
                panels[pos] = panel_result

        total_tables = sum(len(p.tables) for p in panels.values())
        logger.info(
            "DI extraction complete: %d panels, %d total tables",
            len(panels), total_tables,
        )
        return DocumentExtractionResult(panels=panels)
