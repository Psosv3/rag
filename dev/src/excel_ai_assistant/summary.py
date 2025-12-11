from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from textwrap import shorten
from typing import Any, Dict, List

__all__ = ["process_workbooks_concurrently"]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Cell:
    """Represents a single cell value in a summarized workbook row."""
    raw: str
    value: Any
    is_number: bool


@dataclass(slots=True)
class SheetRow:
    """Represents a non-empty row as described in the textual workbook summary."""
    row_index: int
    columns: Dict[int, Cell]


@dataclass(slots=True)
class SheetSummary:
    """Holds parsed information about a single sheet."""
    name: str
    n_rows: int
    n_cols: int
    non_empty_rows: List[SheetRow] = field(default_factory=list)
    cross_sheet_refs: List[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkbookSummary:
    """Container for all sheets belonging to one workbook."""
    sheets: List[SheetSummary]


# ---------------------------------------------------------------------------
# Regex patterns (compiled once for speed)
# ---------------------------------------------------------------------------

_WORKBOOK_BLOCK_RE = re.compile(
    r"=== WORKBOOK SUMMARY START ===(.*?)=== WORKBOOK SUMMARY END ===",
    re.DOTALL,
)

_ROW_RE = re.compile(r"Row\s+(\d+):\s*(.*)$")
_COL_RE = re.compile(r"Column(\d+)=('|\")(.*?)\2")


# ---------------------------------------------------------------------------
# Parsing utilities
# ---------------------------------------------------------------------------


def _split_into_workbook_blocks(raw: str) -> List[str]:
    """
    Split a raw multi-workbook summary string into individual workbook blocks.

    Each block is the text between:
        === WORKBOOK SUMMARY START ===
        === WORKBOOK SUMMARY END ===
    If no markers are found, the entire string is treated as a single block.
    """
    matches = _WORKBOOK_BLOCK_RE.findall(raw)
    if not matches:
        block = raw.strip()
        return [block] if block else []
    return [m.strip() for m in matches if m.strip()]


def _parse_cell_value(text: str) -> Cell:
    """
    Parse a raw cell string into a typed value (float or str).

    The original string is preserved in `raw`. Parsing is intentionally simple:
    - A best-effort float conversion is attempted.
    - On failure, the value is kept as a plain string.
    """
    raw = text
    s = text.strip()
    if not s:
        return Cell(raw=raw, value=s, is_number=False)
    try:
        v = float(s)
        return Cell(raw=raw, value=v, is_number=True)
    except ValueError:
        return Cell(raw=raw, value=s, is_number=False)


def _parse_rows_block(lines: List[str]) -> List[SheetRow]:
    """
    Parse the 'All non-empty rows:' block for a sheet into structured rows.

    The workbook summaries sometimes wrap a logical row across multiple lines.
    This function first merges continuation lines, then extracts rows and cells.
    """
    merged_rows: List[str] = []
    current: str | None = None

    for line in lines:
        if not line.strip():
            continue
        if re.match(r"\s*Row\s+\d+:", line):
            # Starting a new logical row
            if current is not None:
                merged_rows.append(current)
            current = line.strip()
        else:
            # Continuation of the previous logical row
            if current is not None:
                current += " " + line.strip()
            else:
                # Stray continuation-like line; ignore defensively
                continue

    if current is not None:
        merged_rows.append(current)

    result: List[SheetRow] = []
    for row_text in merged_rows:
        m = _ROW_RE.match(row_text)
        if not m:
            continue
        row_idx = int(m.group(1))
        rest = m.group(2)
        cols: Dict[int, Cell] = {}
        for cm in _COL_RE.finditer(rest):
            col_idx = int(cm.group(1))
            val_text = cm.group(3)
            cols[col_idx] = _parse_cell_value(val_text)
        result.append(SheetRow(row_index=row_idx, columns=cols))
    return result


def _parse_workbook_summary_block(block: str) -> WorkbookSummary:
    """
    Parse a single workbook summary block into a WorkbookSummary structure.
    """
    lines = [ln.rstrip("\n") for ln in block.splitlines()]
    sheets: List[SheetSummary] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("Sheet:"):
            # Sheet header
            name = line.split(":", 1)[1].strip()

            n_rows = 0
            n_cols = 0
            i += 1

            # Size line
            if i < len(lines):
                size_line = lines[i].strip()
                m_size = re.search(r"Size:\s*(\d+)\s*rows x\s*(\d+)\s*cols", size_line)
                if m_size:
                    n_rows = int(m_size.group(1))
                    n_cols = int(m_size.group(2))
                    i += 1

            non_empty_rows: List[SheetRow] = []
            cross_refs: List[str] = []

            # "All non-empty rows:" section (may be empty)
            if i < len(lines) and lines[i].strip().startswith("All non-empty rows:"):
                i += 1
                rows_block_lines: List[str] = []
                while i < len(lines):
                    raw_line = lines[i]
                    stripped = raw_line.strip()

                    if stripped.startswith("Sheet:") or stripped.startswith(
                        "=== WORKBOOK SUMMARY END ==="
                    ):
                        break

                    if stripped.startswith("Cross-sheet references:"):
                        refs = stripped.split(":", 1)[1].strip()
                        if refs:
                            cross_refs.extend(
                                r.strip() for r in refs.split(",") if r.strip()
                            )
                        i += 1
                        continue

                    rows_block_lines.append(raw_line)
                    i += 1

                non_empty_rows = _parse_rows_block(rows_block_lines)

            # Additional cross-sheet references directly after the rows block
            while i < len(lines) and lines[i].strip().startswith(
                "Cross-sheet references:"
            ):
                refs_line = lines[i].strip()
                refs = refs_line.split(":", 1)[1].strip()
                if refs:
                    cross_refs.extend(r.strip() for r in refs.split(",") if r.strip())
                i += 1

            sheets.append(
                SheetSummary(
                    name=name,
                    n_rows=n_rows,
                    n_cols=n_cols,
                    non_empty_rows=non_empty_rows,
                    cross_sheet_refs=cross_refs,
                )
            )
            continue  # We already advanced `i` within the sheet block

        i += 1

    return WorkbookSummary(sheets=sheets)


# ---------------------------------------------------------------------------
# Analysis and rendering
# ---------------------------------------------------------------------------


def _classify_row(row: SheetRow) -> Dict[str, Any]:
    """
    Inspect a row to identify a label, textual description, and numeric series.
    """
    if not row.columns:
        return {}

    label_col_idx = min(row.columns.keys())
    label_cell = row.columns[label_col_idx]
    label = str(label_cell.value)

    # Separate numeric and textual cells (excluding the label itself)
    value_cells = [cell for idx, cell in sorted(row.columns.items()) if idx != label_col_idx]
    numeric_values = [c.value for c in value_cells if c.is_number]
    text_values = [str(c.value) for c in value_cells if not c.is_number]

    longest_text_len = max((len(t) for t in text_values), default=0)
    has_description = longest_text_len >= 80  # heuristically considered a description

    numeric_summary = None
    if len(numeric_values) >= 2:
        first = numeric_values[0]
        last = numeric_values[-1]
        if last > first:
            trend = "increasing"
        elif last < first:
            trend = "decreasing"
        else:
            trend = "stable"
        numeric_summary = {
            "count": len(numeric_values),
            "first": first,
            "last": last,
            "trend": trend,
        }

    return {
        "label": label,
        "label_col_idx": label_col_idx,
        "numeric_values": numeric_values,
        "text_values": text_values,
        "longest_text": longest_text_len,
        "has_description": has_description,
        "numeric_summary": numeric_summary,
    }


def _render_sheet_summary(sheet: SheetSummary, sheet_index: int) -> str:
    """
    Render a single sheet into a compact, human-friendly Markdown-like summary.
    """
    lines: List[str] = []

    non_empty_count = len(sheet.non_empty_rows)
    lines.append(
        f"## Sheet {sheet_index + 1}: {sheet.name} "
        f"({sheet.n_rows} rows × {sheet.n_cols} cols)"
    )
    lines.append(f"- Non-empty rows: {non_empty_count}")

    if sheet.cross_sheet_refs:
        refs_str = ", ".join(sorted(set(sheet.cross_sheet_refs)))
        lines.append(f"- Cross-sheet references: {refs_str}")

    # Analyze each row
    analyzed = [_classify_row(r) for r in sheet.non_empty_rows]

    # Distinct labels in order of first appearance (deterministic)
    labels = [a.get("label") for a in analyzed if a.get("label")]
    distinct_labels: List[str] = []
    seen: set[str] = set()
    for lbl in labels:
        if lbl not in seen:
            seen.add(lbl)
            distinct_labels.append(lbl)
    lines.append(f"- Distinct row labels: {len(distinct_labels)}")

    # Definition-like rows: long textual descriptions
    definitions: List[tuple[SheetRow, Dict[str, Any]]] = [
        (sheet.non_empty_rows[i], a)
        for i, a in enumerate(analyzed)
        if a.get("has_description")
    ]

    if definitions:
        lines.append("### Key definitions")
        for row, meta in definitions[:15]:
            label = meta["label"]
            texts = meta["text_values"]
            desc = max(texts, key=len) if texts else ""
            desc_short = shorten(desc, width=200, placeholder="…")
            lines.append(f"- **{label}** (row {row.row_index}): {desc_short}")

    # Numeric series summarization
    metrics: List[tuple[SheetRow, Dict[str, Any]]] = [
        (sheet.non_empty_rows[i], a)
        for i, a in enumerate(analyzed)
        if a.get("numeric_summary")
    ]

    if metrics:
        lines.append("### Time-based metrics")
        for row, meta in metrics[:20]:
            ns = meta["numeric_summary"]
            label = meta["label"]
            count = ns["count"]
            first = ns["first"]
            last = ns["last"]
            trend = ns["trend"]
            lines.append(
                f"- **{label}** (row {row.row_index}): "
                f"{count} numeric values (first={first:g}, last={last:g}, trend={trend})."
            )

    # If there are no definitions or metrics, at least list the labels
    if not definitions and not metrics and distinct_labels:
        lines.append("### Row labels")
        for lbl in distinct_labels[:30]:
            lines.append(f"- {lbl}")

    lines.append("")  # Trailing blank line for separation
    return "\n".join(lines)


def _render_workbook_summary(wb: WorkbookSummary, index: int) -> str:
    """
    Render an entire workbook into an enhanced Markdown-like summary.
    """
    sheet_names = [s.name for s in wb.sheets]
    total_non_empty = sum(len(s.non_empty_rows) for s in wb.sheets)
    all_refs = sorted({ref for s in wb.sheets for ref in s.cross_sheet_refs})

    lines: List[str] = []
    lines.append(f"# Workbook {index + 1}")
    lines.append("")
    lines.append(f"- Sheets: {len(wb.sheets)}")
    lines.append(f"- Sheet names: {', '.join(sheet_names)}")
    lines.append(f"- Total non-empty rows across sheets: {total_non_empty}")
    if all_refs:
        lines.append(f"- Cross-sheet references used: {', '.join(all_refs)}")
    lines.append("")

    for i, sheet in enumerate(wb.sheets):
        lines.append(_render_sheet_summary(sheet, i))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _process_single_workbook_block(index: int, block: str) -> str:
    """
    Internal helper to parse and render a single workbook block.

    Separated as a top-level function so it can be safely used with executors.
    """
    wb = _parse_workbook_summary_block(block)
    return _render_workbook_summary(wb, index)


def process_workbooks_concurrently(workbook_summary: str) -> str:
    """
    Transform one or more raw workbook summaries into enhanced, easy-to-read text.

    Parameters
    ----------
    workbook_summary : str
        Raw text containing one or more workbook summary blocks delimited by
        '=== WORKBOOK SUMMARY START ===' and '=== WORKBOOK SUMMARY END ==='.

        The function is also tolerant to a string containing a single workbook
        without markers: in that case, the entire string is treated as one block.

    Returns
    -------
    str
        Enhanced, human-readable summary. If multiple workbook blocks are present,
        their enhanced summaries are concatenated in the original order.

    Notes
    -----
    - Designed to be deterministic: output depends only on input contents.
    - Uses a ThreadPoolExecutor to handle many workbook blocks in parallel.
      The concurrency level is automatically capped to avoid oversubscription.
    """
    if not isinstance(workbook_summary, str):
        raise TypeError(
            "workbook_summary must be a string containing one or more workbook summaries."
        )

    blocks = _split_into_workbook_blocks(workbook_summary)
    if not blocks:
        return ""

    # Single-block fast path (avoids thread pool overhead).
    if len(blocks) == 1:
        return _process_single_workbook_block(0, blocks[0])

    max_workers = min(32, len(blocks))
    enhanced_by_index: List[str] = [""] * len(blocks)

    # Thread-based concurrency is safe across platforms and adequate here,
    # as the workload is parsing + string formatting.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(_process_single_workbook_block, idx, block): idx
            for idx, block in enumerate(blocks)
        }
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                enhanced_by_index[idx] = future.result()
            except Exception as exc:  # Defensive: keep other workbooks usable
                enhanced_by_index[idx] = (
                    f"# Workbook {idx + 1}\n\n"
                    f"Failed to process workbook summary due to error: {exc!r}\n"
                )

    return "\n\n".join(enhanced_by_index)
