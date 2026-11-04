"""Orchestrates one question: plan -> execute tools -> compose -> check -> respond.

The LLM decides which tools to call and writes the prose. It never does arithmetic,
and the evidence and caveats in the response come from code, not from the model.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from . import prompts, stub
from .data import DataStore
from .grounding import check_answer
from .llm import LLMClient, LLMError
from .pipeline_types import Composition, Plan
from .policy import Policy
from .render import eur, render_answer
from .tools import Tools

log = logging.getLogger(__name__)
AUDIT_LOG = Path(__file__).resolve().parents[1] / "logs" / "audit.jsonl"
MAX_ROWS_FOR_LLM = 40


class PlanningFailed(Exception):
    pass


class Assistant:
    def __init__(self, store: DataStore, policy: Policy, client: LLMClient | None):
        self.store = store
        self.policy = policy
        self.client = client
        self.tools = Tools(store, policy)
        self.mode = {
            "is_stub": client is None,
            "provider": "stub" if client is None else type(client).__name__.replace("Client", "").lower(),
            "model": None if client is None else client.model,
        }

    def ask(self, question: str) -> dict:
        started = time.monotonic()
        plan = self._plan(question)
        results = [self.tools.run(call, f"D{i}") for i, call in enumerate(plan.tool_calls, 1)]
        answer, clauses, grounding, source = self._compose(question, plan, results)
        response = {
            "trace_id": uuid.uuid4().hex,
            "answer": answer,
            "answer_source": source,
            "route": {"decision": plan.route, "reasoning": plan.reasoning},
            "evidence": {"policy": [self._clause_payload(c) for c in clauses], "data": results},
            "assumptions": self._assumptions(results),
            "grounding": grounding,
            "llm": self.mode,
            "fx": vars(self.store.fx.info),
            "provenance": {"data_version": self.store.data_version,
                           "prompt_version": prompts.PROMPT_VERSION},
        }
        self._audit(question, plan, response, time.monotonic() - started)
        return response

    # ---- planning ---------------------------------------------------------------------

    def _plan(self, question: str) -> Plan:
        if self.client is None:
            plan = stub.plan(question)
            self._validate_plan(plan)
            return plan

        system = prompts.PLANNER_SYSTEM.format(policy=self.policy.text)
        schema = Plan.model_json_schema()
        error = ""
        for _ in range(2):
            raw = self.client.complete_json(
                system, question + (prompts.RETRY_SUFFIX.format(error=error) if error else ""), schema
            )
            try:
                plan = Plan.model_validate(raw)
                self._validate_plan(plan)
                return plan
            except (ValidationError, ValueError) as exc:
                error = str(exc)
                log.warning("Rejected plan: %s", error)
        raise PlanningFailed(error)

    def _validate_plan(self, plan: Plan) -> None:
        unknown = set(plan.policy_clauses) - set(self.policy.clauses)
        if unknown:
            raise ValueError(f"Unknown policy clauses: {sorted(unknown)}")
        if plan.route == "none" and (plan.tool_calls or plan.policy_clauses):
            raise ValueError('Route "none" cannot include tool calls or clauses')
        if plan.route in ("data", "both") and not plan.tool_calls:
            raise ValueError(f'Route "{plan.route}" requires at least one tool call')
        if plan.route in ("policy", "both") and not plan.policy_clauses:
            raise ValueError(f'Route "{plan.route}" requires policy_clauses')
        if plan.route == "policy" and any(c.tool != "required_approver" for c in plan.tool_calls):
            raise ValueError('Route "policy" may only call required_approver')

    # ---- composing --------------------------------------------------------------------

    def _compose(self, question: str, plan: Plan, results: list[dict]):
        template = render_answer(plan, results, self.policy, question)
        clauses = list(plan.policy_clauses)
        if plan.route == "none":
            return template, [], {"status": "declined", "problems": []}, "template"
        if self.client is None:
            return template, clauses, {"status": "template", "problems": []}, "template"

        system = prompts.COMPOSER_SYSTEM.format(policy=self.policy.text)
        user = prompts.COMPOSER_USER.format(
            question=question, evidence=json.dumps([_for_llm(r) for r in results], indent=1)
        )
        problems: list[str] = []
        for _ in range(2):
            suffix = prompts.RETRY_SUFFIX.format(error="; ".join(problems)) if problems else ""
            try:
                raw = self.client.complete_json(system, user + suffix, Composition.model_json_schema())
                composed = Composition.model_validate(raw)
            except (LLMError, ValidationError) as exc:
                # Tools already ran, so a model failure need not lose the answer.
                problems = [f"Composition failed: {exc}"]
                continue
            problems = check_answer(
                composed.answer, results, self.policy.text, question, composed.cited_clauses,
                composed.cited_results, set(self.policy.clauses), requires_result=bool(results),
            )
            if not problems:
                merged = clauses + [c for c in composed.cited_clauses if c not in clauses]
                return composed.answer, merged, {"status": "passed", "problems": []}, "llm"
            log.warning("Rejected answer: %s", problems)
        return template, clauses, {"status": "fallback_to_template", "problems": problems}, "template"

    # ---- response parts ---------------------------------------------------------------

    def _clause_payload(self, clause_id: str) -> dict:
        clause = self.policy.clauses[clause_id]
        return {"id": clause.id, "section": clause.section, "text": clause.text, "line": clause.line}

    def _assumptions(self, results: list[dict]) -> list[str]:
        notes: list[str] = []
        needs_fx = any(r["tool"] == "query_invoices" or r.get("rows") or
                       r.get("currency", "EUR") != "EUR" for r in results)
        if needs_fx:
            notes.append(self.store.fx.info.note)
        for result in results:
            if result["tool"] == "required_approver" and result["currency"] != "EUR" \
                    and "invoice_date" not in result["parameters"]:
                notes.append("No invoice date was given, so the EUR value is approximate, and "
                             "could change the approval band near a threshold.")
            if result["tool"] != "query_invoices" or not result["totals"]["invoice_count"]:
                continue
            notes.append('"Spend" means invoiced value net of credit notes. The data has no '
                         "payment status, so this is not cash paid.")
            flags = result["control_flags"]
            parts = []
            if flags["non_active_vendor_count"]:
                parts.append(f"{flags['non_active_vendor_count']} from non-active vendors "
                             f"({eur(flags['non_active_vendor_eur'])}, §4.1)")
            if flags["missing_approver_count"]:
                parts.append(f"{flags['missing_approver_count']} with no approver "
                             f"({eur(flags['missing_approver_eur'])}, §3.1)")
            if flags["missing_po_count"]:
                parts.append(f"{flags['missing_po_count']} with no PO "
                             f"({eur(flags['missing_po_eur'])}, §2.2)")
            if parts:
                notes.append(f"{result['id']} includes invoices with open control issues: "
                             + "; ".join(parts) + ". These may overlap.")
        return list(dict.fromkeys(notes))

    def _audit(self, question: str, plan: Plan, response: dict, seconds: float) -> None:
        """Append-only trail for §8.2. Local JSONL here; a tamper-evident store in production."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": response["trace_id"],
            "question": question,
            "plan": plan.model_dump(),
            "invoices_used": sorted({row["invoice_number"] for r in response["evidence"]["data"]
                                     for row in r.get("rows", [])}),
            "answer": response["answer"],
            "answer_source": response["answer_source"],
            "grounding": response["grounding"],
            "llm": response["llm"],
            "fx_mode": response["fx"]["mode"],
            "provenance": response["provenance"],
            "seconds": round(seconds, 3),
        }
        try:
            AUDIT_LOG.parent.mkdir(exist_ok=True)
            with AUDIT_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError:
            log.exception("Could not write the audit record")


def _for_llm(result: dict) -> dict:
    """Keeps prompts small. Totals and groups are complete; only source rows are capped."""
    rows = result.get("rows", [])
    if len(rows) <= MAX_ROWS_FOR_LLM:
        return result
    return {**result, "rows": rows[:MAX_ROWS_FOR_LLM],
            "rows_note": f"Showing {MAX_ROWS_FOR_LLM} of {len(rows)} source rows; totals cover all."}
