# excel_ai_assistant/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal


@dataclass
class CellInfo:
    sheet_name: str
    address: str  # e.g. "B12"
    value: Any    # cached value (including formula result if available)
    formula: Optional[str] = None


@dataclass
class LabeledValue:
    """
    Represents a semantic association like:

        Sheet1!B1: "Revenue year 1"  -->  Sheet1!C1: 324654532

    orientation:
        - "horizontal": label and value on same row, adjacent columns
        - "vertical":   label and value on same column, adjacent rows
    """

    sheet_name: str
    label: str
    label_address: str
    value_address: str
    value: Any
    orientation: Literal["horizontal", "vertical"]


@dataclass
class SheetSummary:
    name: str
    n_rows: int
    n_cols: int
    headers: List[str] = field(default_factory=list)
    sample_rows: List[Dict[str, Any]] = field(default_factory=list)
    formula_cells: List[CellInfo] = field(default_factory=list)
    cross_sheet_references: List[str] = field(default_factory=list)
    labeled_values: List[LabeledValue] = field(default_factory=list)

    def to_text_block(self, max_sample_rows: int = 5, max_labeled_values: int = 15) -> str:
        """Convert summary to a compact text block for LLM context."""
        sample_rows = self.sample_rows[:max_sample_rows]
        labeled_values = self.labeled_values[:max_labeled_values]

        lines: List[str] = [
            f"Sheet: {self.name}",
            f"Size: {self.n_rows} rows x {self.n_cols} cols",
        ]

        if self.headers:
            lines.append(f"Headers: {', '.join(self.headers)}")

        if sample_rows:
            lines.append("Sample rows:")
            for i, row in enumerate(sample_rows, start=1):
                row_str = ", ".join(f"{k}={v!r}" for k, v in row.items())
                lines.append(f"  Row {i}: {row_str}")

        if labeled_values:
            lines.append("Key labeled values (label -> value):")
            for lv in labeled_values:
                lines.append(
                    f"  [{lv.orientation}] "
                    f"{self.name}!{lv.label_address}={lv.label!r} "
                    f"-> {self.name}!{lv.value_address}={lv.value!r}"
                )

        if self.cross_sheet_references:
            refs_str = ", ".join(sorted(set(self.cross_sheet_references)))
            lines.append(f"Cross-sheet references: {refs_str}")

        if self.formula_cells:
            formulas_preview: List[str] = []
            for cell in self.formula_cells[:5]:
                if not cell.formula:
                    continue
                desc = f"{cell.sheet_name}!{cell.address}: {cell.formula}"
                if cell.value is not None:
                    desc += f" (value={cell.value!r})"
                formulas_preview.append(desc)

            if formulas_preview:
                lines.append("Example formulas:")
                lines.extend(f"  {f}" for f in formulas_preview)

        return "\n".join(lines)


@dataclass
class WorkbookSummary:
    file_id: str
    sheets: List[SheetSummary] = field(default_factory=list)

    def to_text(self, max_sheets: int = 10) -> str:
        """Convert the whole workbook summary into a compact text representation."""
        selected_sheets = self.sheets[:max_sheets]
        blocks = [sheet.to_text_block() for sheet in selected_sheets]
        return "\n\n".join(blocks)
