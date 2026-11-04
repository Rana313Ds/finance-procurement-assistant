"""Parses the policy into citable clauses, so evidence quotes the file verbatim.

The LLM only ever cites a clause id; the text shown to the analyst is looked up
here, which means a quote cannot be invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .data import DATA_DIR

_NUMBER = r"\d[\d,]*(?:\.\d+)?"


@dataclass(frozen=True)
class Clause:
    id: str
    section: str
    text: str
    line: int


@dataclass(frozen=True)
class ApprovalBand:
    label: str
    upper_eur: float | None  # None means no upper limit
    approver: str


class Policy:
    def __init__(self, path: Path = DATA_DIR / "procurement_policy.md"):
        self.text = path.read_text(encoding="utf-8")  # Windows defaults to cp1252, which garbles "–".
        self.clauses: dict[str, Clause] = {}
        self.bands: list[ApprovalBand] = []
        self._parse()
        if not self.bands:
            raise ValueError("Approval table not found in policy")

    def _parse(self) -> None:
        section_no, section_title = "", ""
        body: list[str] = []
        body_line = 0

        def flush() -> None:
            if body:
                self.clauses[section_no] = Clause(
                    section_no, section_title, "\n".join(body), body_line
                )
                body.clear()

        for line_no, raw in enumerate(self.text.splitlines(), start=1):
            line = raw.strip()
            heading = re.match(r"## (\d+)\. (.+)", line)
            clause = re.match(r"(\d+\.\d+) (.+)", line)
            if heading:
                flush()
                section_no, section_title = heading.groups()
            elif clause and section_no:
                flush()
                clause_id, text = clause.groups()
                self.clauses[clause_id] = Clause(clause_id, section_title, text, line_no)
            elif line and section_no:
                if not body:
                    body_line = line_no
                body.append(line)
                self._parse_band(line)
        flush()

    def _parse_band(self, line: str) -> None:
        match = re.match(rf"\| ((?:Up to|Above|{_NUMBER}).*?) \| (.+?) \|$", line)
        if not match:
            return
        label, approver = match.groups()
        numbers = re.findall(_NUMBER, label)
        upper = None if label.startswith("Above") else float(numbers[-1].replace(",", ""))
        self.bands.append(ApprovalBand(label, upper, approver))

    def approver_for(self, amount_eur: float) -> ApprovalBand:
        value = round(abs(amount_eur), 2)
        for band in self.bands:
            if band.upper_eur is None or value <= band.upper_eur:
                return band
        raise AssertionError("Approval bands must end with an open upper limit")
