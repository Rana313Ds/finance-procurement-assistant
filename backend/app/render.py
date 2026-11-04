"""Deterministic answers built directly from tool results.

Used in stub mode, and as the fallback when an LLM answer fails the grounding checks.
"""
from __future__ import annotations

import re

from .pipeline_types import Plan
from .policy import Policy

MAX_LISTED_ROWS = 25
LIST_INTENT = re.compile(r"\b(which|list|show|what are the|identify|find)\b")
AVERAGE_INTENT = re.compile(r"\b(average|avg|mean|typical)\b")
COUNT_INTENT = re.compile(r"\b(how many|number of|count)\b")


def eur(value: float) -> str:
    return f"EUR {value:,.2f}"


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def render_answer(plan: Plan, results: list[dict], policy: Policy, question: str = "") -> str:
    if plan.route == "none":
        return ("I can't answer this from the invoice data or the policy excerpt. "
                f"{plan.reasoning} Please check with Procurement Excellence or the source system.")
    q = question.lower()
    parts = [_render_result(r, q) for r in results]
    # An invoice check already cites its clauses line by line.
    has_check = any(r["tool"] == "check_invoice" for r in results)
    if not has_check and (not results or plan.route == "both"):
        parts += [_render_clause(policy, c) for c in plan.policy_clauses]
    return "\n\n".join(parts)


def _render_clause(policy: Policy, clause_id: str) -> str:
    clause = policy.clauses[clause_id]
    if clause_id == "3":
        rows = "; ".join(f"{b.label}: {b.approver}" for b in policy.bands)
        return f"§3 approval thresholds (EUR): {rows}."
    return f"§{clause.id}: " + clause.text.replace("**", "")


def _render_result(result: dict, q: str = "") -> str:
    if result["tool"] == "required_approver":
        converted = "" if result["currency"] == "EUR" else (
            f" ({result['currency']} {result['amount']:,.2f} converts to {eur(result['amount_eur'])})"
        )
        return (f"An invoice of {eur(result['amount_eur'])}{converted} falls in the "
                f"{result['band_eur']} band, so it requires approval by the "
                f"{result['required_approver']} (§3). The approver cannot be the requester (§7.1), "
                "and self-approval is prohibited (§7.2).")
    if result["tool"] == "check_invoice":
        if not result["found"]:
            return f"No invoice {result['parameters']['invoice_number']} exists in the 2025 data."
        row = result["rows"][0]
        converted = "" if row["currency"] == "EUR" else f" ({eur(row['amount_eur'])})"
        failed = [c["check"] for c in result["checks"] if c["status"] == "fail"]
        verdict = (f"Do not process yet: failed {', '.join(failed)}." if failed else
                   "No control failed, but the checks marked cannot_verify still need a manual review.")
        lines = [f"{row['invoice_number']} from {row['vendor_name']}: {row['currency']} "
                 f"{row['amount']:,.2f}{converted}. {verdict}"]
        lines += [f"- {c['check']} [{c['status']}]: {c['detail']} (§{c['clause']})"
                  for c in result["checks"]]
        return "\n".join(lines)
    return _render_query(result, q)


def _render_query(result: dict, q: str = "") -> str:
    totals = result["totals"]
    params = result["parameters"]
    if totals["invoice_count"] == 0:
        return "No invoices match those criteria."

    if result["groups"]:
        by_count = params.get("sort_by") == "invoice_count"
        lines = [f"{i}. {g['key']}: {eur(g['net_eur'])} ({plural(g['invoice_count'], 'invoice')})"
                 for i, g in enumerate(result["groups"], 1)]
        if len(lines) == 1:
            g = result["groups"][0]
            measure = plural(g["invoice_count"], "invoice") if by_count else f"{eur(g['net_eur'])} net"
            return (f"{g['key']}, with {measure}"
                    + (f" ({eur(g['net_eur'])} net)." if by_count else
                       f" across {plural(g['invoice_count'], 'invoice')}."))
        ranked = "invoice count" if by_count else "net spend"
        return (f"Results ({len(lines)} groups, ranked by {ranked}, net of credit notes):\n"
                + "\n".join(lines))

    rows = result.get("rows") or []
    if params.get("top_n"):  # largest / smallest individual invoices
        rows = sorted(rows, key=lambda r: r["amount_eur"], reverse=params.get("order", "desc") == "desc")
        which = "largest" if params.get("order", "desc") == "desc" else "smallest"
        head = (f"The {which} invoice" if len(rows) == 1 else f"The {which} {len(rows)} invoices")
        return (f"{head} (of {plural(totals['invoice_count'], 'matching invoice')}):\n"
                + "\n".join(_row_line(r) for r in rows))

    if totals["credit_note_count"] == totals["invoice_count"]:
        text = (f"There {'is' if totals['invoice_count'] == 1 else 'are'} "
                f"{plural(totals['invoice_count'], 'credit note')} totalling {eur(totals['credit_notes_eur'])}.")
    else:
        text = f"Net spend is {eur(totals['net_eur'])} across {plural(totals['invoice_count'], 'invoice')}."
        if totals["credit_note_count"]:
            text += (f" That is {eur(totals['gross_eur'])} gross, less "
                     f"{plural(totals['credit_note_count'], 'credit note')} of {eur(totals['credit_notes_eur'])}.")

    native = {c: v for c, v in totals["native_net"].items() if c != "EUR"}
    if params.get("filters", {}).get("currency") and native:
        text += " In invoice currency: " + ", ".join(f"{c} {v:,.2f}" for c, v in native.items()) + "."
    if COUNT_INTENT.search(q):
        text = f"There {'is' if totals['invoice_count'] == 1 else 'are'} {plural(totals['invoice_count'], 'invoice')}. " + text
    if AVERAGE_INTENT.search(q):
        text += (f" The average is {eur(totals['average_eur'])} per invoice (net spend divided by "
                 f"{plural(totals['invoice_count'], 'invoice')}, credit notes included).")

    if rows and (LIST_INTENT.search(q) or len(rows) <= 5):
        ordered = sorted(rows, key=lambda r: -r["amount_eur"])
        shown = ordered[:MAX_LISTED_ROWS]
        text += "\n\n" + ("Invoices:" if len(shown) == len(rows) else
                          f"Largest {len(shown)} of {len(rows)} invoices (all are under Sources):")
        text += "\n" + "\n".join(_row_line(r) for r in shown)
    return text


def _row_line(r: dict) -> str:
    native = "" if r["currency"] == "EUR" else f" ({r['currency']} {r['amount']:,.2f})"
    no_po = not r["po_number"] and abs(r["amount_eur"]) >= 1000  # §2.1 threshold
    flags = [label for label, bad in (("no PO", no_po), ("no approver", not r["approved_by"]),
                                      (r["vendor_status"], r["vendor_status"] != "ACTIVE")) if bad]
    return (f"- {r['invoice_number']}, {r['invoice_date']}, {r['vendor_name']}: {eur(r['amount_eur'])}{native}"
            + (f" [{', '.join(flags)}]" if flags else ""))
