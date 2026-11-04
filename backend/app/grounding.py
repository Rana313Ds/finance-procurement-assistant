"""Mechanical hallucination checks on composed answers.

If any check fails the LLM gets one retry, then the answer is replaced by the
deterministic template. These checks show a number exists in the evidence, not that
it is used correctly; that gap is what the evaluation in the README is for.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

_ID = re.compile(r"\b(?:INV|PO|CC|V)-[A-Z]*-?\d+\b", re.IGNORECASE)
_CLAUSE_REF = re.compile(r"§\s*\d+(?:\.\d+)?")
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
_QUARTER = re.compile(r"\bQ[1-4]\b")
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    found = set()
    for token in _NUMBER.findall(text):
        try:
            found.add(Decimal(token.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return found


def check_answer(answer: str, evidence: list[dict], policy_text: str, question: str,
                 cited_clauses: list[str], cited_results: list[str], valid_clauses: set[str],
                 requires_result: bool) -> list[str]:
    """Returns a list of problems; an empty list means the answer passed."""
    problems = []
    evidence_text = json.dumps(evidence)

    invoice_ids = {i.upper() for i in re.findall(r"INV-\d+", answer, re.IGNORECASE)}
    known_ids = set(re.findall(r"INV-\d+", evidence_text))
    if invoice_ids - known_ids:
        problems.append(f"Invoice ids not in evidence: {sorted(invoice_ids - known_ids)}")

    stripped = _ID.sub(" ", answer)
    stripped = _CLAUSE_REF.sub(" ", stripped)
    stripped = _QUARTER.sub(" ", stripped)
    stripped = _LIST_MARKER.sub(" ", stripped)
    allowed = _numbers(evidence_text) | _numbers(policy_text) | _numbers(question)
    unknown = _numbers(stripped) - allowed
    if unknown:
        problems.append(
            "Figures not in evidence: " + ", ".join(sorted(f"{n:f}" for n in unknown))
        )

    bad_clauses = set(cited_clauses) - valid_clauses
    if bad_clauses:
        problems.append(f"Cited clauses that do not exist: {sorted(bad_clauses)}")
    referenced = set(re.findall(r"§\s*(\d+(?:\.\d+)?)", answer))
    if referenced - valid_clauses:
        problems.append(f"Answer refers to clauses that do not exist: {sorted(referenced - valid_clauses)}")

    result_ids = {e["id"] for e in evidence}
    if set(cited_results) - result_ids:
        problems.append(f"Cited results that do not exist: {sorted(set(cited_results) - result_ids)}")
    if requires_result and not set(cited_results) & result_ids:
        problems.append("The answer must cite at least one evidence result")
    return problems
