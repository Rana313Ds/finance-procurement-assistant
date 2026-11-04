"""Covers the deterministic core and the failure paths, using a scripted fake LLM.

Expected figures are recomputed with the csv module, independently of the pandas code.
"""
import csv
import json
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.data import DATA_DIR, DataStore
from app.grounding import check_answer
from app.llm import AnthropicClient, LLMError, OllamaClient
from app.main import app
from app.pipeline import Assistant, PlanningFailed
from app.policy import Policy
from scripts.fetch_ecb_rates import extract_2025

RATES = {"EUR": 1.0, "USD": 1.13, "GBP": 0.85687}
store, policy = DataStore(), Policy()


def source_rows():
    vendors = {v["vendor_id"]: v for v in csv.DictReader((DATA_DIR / "vendor_master.csv").open(encoding="utf-8"))}
    rows = list(csv.DictReader((DATA_DIR / "invoices_2025_clean.csv").open(encoding="utf-8")))
    for row in rows:
        row["eur"] = round(float(row["amount"]) / RATES[row["currency"]], 2)
        row["vendor"] = vendors[row["vendor_id"]]
    return rows


def stub_assistant():
    return Assistant(store, policy, None)


class FakeLLM:
    model = "fake"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def complete_json(self, system, user, schema, max_tokens=1500):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


SPAIN_PLAN = {"route": "data", "reasoning": "Needs figures.", "tool_calls": [
    {"tool": "query_invoices", "filters": {"country": ["Spain"]}}]}


def spain_total():
    rows = [r for r in source_rows() if r["vendor"]["country"] == "Spain"]
    return round(sum(r["eur"] for r in rows), 2), len(rows)


def test_spain_total_matches_independent_calculation():
    response = stub_assistant().ask("What is our total spend with vendors based in Spain?")
    total, count = spain_total()
    result = response["evidence"]["data"][0]
    assert (result["totals"]["net_eur"], result["totals"]["invoice_count"]) == (total, count)
    assert response["route"]["decision"] == "data"
    assert {r["invoice_number"] for r in result["rows"]} == {
        r["invoice_number"] for r in source_rows() if r["vendor"]["country"] == "Spain"}


def test_top_5_matches_independent_calculation():
    response = stub_assistant().ask("What are our top 5 vendors by total spend in 2025?")
    spend = {}
    for row in source_rows():
        spend[row["vendor_name"]] = round(spend.get(row["vendor_name"], 0) + row["eur"], 2)
    expected = sorted(spend.items(), key=lambda item: -item[1])[:5]
    groups = response["evidence"]["data"][0]["groups"]
    assert [(g["key"], g["net_eur"]) for g in groups] == expected


def test_evidence_rows_add_up_to_reported_group():
    result = stub_assistant().ask("Top 3 vendors by spend")["evidence"]["data"][0]
    assert round(sum(g["net_eur"] for g in result["groups"]), 2) == round(
        sum(r["amount_eur"] for r in result["rows"]), 2)


@pytest.mark.parametrize("amount,approver", [
    (5000, "Cost Center Owner"), (5000.01, "Department Head"), (50000, "Department Head"),
    (50000.01, "Finance Director"), (60000, "Finance Director"), (250000, "Finance Director"),
    (250000.01, "CFO + Procurement Excellence review"), (-60000, "Finance Director"),
])
def test_approval_boundaries(amount, approver):
    assert policy.approver_for(amount).approver == approver


# ---- stub routing regressions: each recomputed independently from the CSVs --------------

def first_query(question):
    response = stub_assistant().ask(question)
    return response, response["evidence"]["data"][0]


def total_where(predicate):
    rows = [r for r in source_rows() if predicate(r)]
    return round(sum(r["eur"] for r in rows), 2), len(rows)


def test_policy_text_is_read_as_utf8():
    assert "â€" not in policy.text
    assert any("–" in band.label for band in policy.bands)


def test_vendor_with_most_invoices():
    counts = {}
    for row in source_rows():
        counts[row["vendor_name"]] = counts.get(row["vendor_name"], 0) + 1
    name, count = max(counts.items(), key=lambda item: item[1])
    response, result = first_query("Which vendor has the most invoices?")
    assert [(g["key"], g["invoice_count"]) for g in result["groups"]] == [(name, count)]
    assert name in response["answer"]


def test_biggest_vendor_is_top_one_by_spend():
    spend = {}
    for row in source_rows():
        spend[row["vendor_name"]] = round(spend.get(row["vendor_name"], 0) + row["eur"], 2)
    name = max(spend, key=spend.get)
    response, result = first_query("Who is our biggest vendor?")
    assert [g["key"] for g in result["groups"]] == [name]
    assert response["answer"].startswith(name)


@pytest.mark.parametrize("question,pick", [("What is the largest invoice?", max),
                                           ("Smallest invoice", min)])
def test_largest_and_smallest_single_invoice(question, pick):
    invoices = [r for r in source_rows() if float(r["amount"]) >= 0]
    expected = pick(invoices, key=lambda r: r["eur"])["invoice_number"]
    response, result = first_query(question)
    assert [r["invoice_number"] for r in result["rows"]] == [expected]
    assert expected in response["answer"]


@pytest.mark.parametrize("question,predicate", [
    ("How much did we spend on IT services?", lambda r: r["vendor"]["category"] == "IT Services"),
    ("How much did we spend with Spanish vendors?", lambda r: r["vendor"]["country"] == "Spain"),
    ("How much was spent in the United Kingdom?", lambda r: r["vendor"]["country"] == "UK"),
])
def test_category_and_country_phrasings_filter_correctly(question, predicate):
    _, result = first_query(question)
    assert (result["totals"]["net_eur"], result["totals"]["invoice_count"]) == total_where(predicate)


def test_monthly_spend_groups_by_month():
    _, result = first_query("Monthly spend")
    assert len(result["groups"]) == 12


def test_which_invoices_lists_them_in_the_answer():
    response, result = first_query("Which invoices from on hold vendors need escalation?")
    assert result["groups"] is None
    for row in result["rows"]:
        assert row["invoice_number"] in response["answer"]


def test_average_is_reported():
    total, count = total_where(lambda r: True)
    response, _ = first_query("What is the average invoice amount?")
    assert f"{total / count:,.2f}" in response["answer"]


def test_currency_question_reports_native_amount():
    native = round(sum(float(r["amount"]) for r in source_rows() if r["currency"] == "GBP"), 2)
    response, _ = first_query("What is our spend in GBP?")
    assert f"GBP {native:,.2f}" in response["answer"]


@pytest.mark.parametrize("question,approver", [
    ("Who approves a 2025 invoice of EUR 60,000?", "Finance Director"),
    ("Who approves invoices above 250k?", "CFO + Procurement Excellence review"),
    ("Who approves a Q1 invoice of 4,000 EUR?", "Cost Center Owner"),
    ("Who approves an invoice over EUR 5,000?", "Department Head"),
    ("Who approves an invoice of EUR 5,000?", "Cost Center Owner"),
])
def test_approval_amount_parsing(question, approver):
    _, result = first_query(question)
    assert result["required_approver"] == approver


def test_approver_question_is_policy_route_with_clause_evidence():
    response = stub_assistant().ask("Who is allowed to approve an invoice of EUR 60,000?")
    assert response["route"]["decision"] == "policy"
    assert "Finance Director" in response["answer"]
    assert "3" in [c["id"] for c in response["evidence"]["policy"]]


def test_invoice_check_flags_failures_and_unverifiable_controls():
    response = stub_assistant().ask("Can INV-20005 be paid?")
    checks = {c["check"]: c["status"] for c in response["evidence"]["data"][0]["checks"]}
    assert checks["Approver recorded"] == "fail"
    assert checks["Approver authority"] == "cannot_verify"
    assert checks["Segregation of duties"] == "cannot_verify"


def test_inactive_vendor_invoice_fails_vendor_check():
    response = stub_assistant().ask("Check INV-20004")
    checks = {c["check"]: c["status"] for c in response["evidence"]["data"][0]["checks"]}
    assert checks["Vendor status"] == "fail"


@pytest.mark.parametrize("question", ["Has INV-20001 been paid?", "What was spend in 2024?",
                                      "What's the weather?"])
def test_unanswerable_questions_are_declined_without_evidence(question):
    response = stub_assistant().ask(question)
    assert response["route"]["decision"] == "none"
    assert response["grounding"]["status"] == "declined"
    assert response["evidence"] == {"policy": [], "data": []}


def test_every_clause_quote_is_verbatim_from_the_policy():
    for clause in policy.clauses.values():
        for line in clause.text.splitlines():
            assert line in policy.text


def test_llm_answer_that_passes_checks_is_used():
    total, count = spain_total()
    llm = FakeLLM(SPAIN_PLAN, {"answer": f"Net spend is EUR {total:,.2f} across {count} invoices.",
                               "cited_results": ["D1"], "cited_clauses": []})
    response = Assistant(store, policy, llm).ask("Spain spend?")
    assert response["answer_source"] == "llm"
    assert response["grounding"]["status"] == "passed"
    assert response["llm"]["is_stub"] is False


def test_hallucinated_figure_is_retried_then_replaced_by_template():
    total, _ = spain_total()
    bad = {"answer": "Net spend is EUR 999,999.99.", "cited_results": ["D1"], "cited_clauses": []}
    llm = FakeLLM(SPAIN_PLAN, bad, bad)
    response = Assistant(store, policy, llm).ask("Spain spend?")
    assert llm.calls == 3
    assert response["answer_source"] == "template"
    assert response["grounding"]["status"] == "fallback_to_template"
    assert f"{total:,.2f}" in response["answer"]
    assert "999,999.99" not in response["answer"]


def test_composer_outage_still_returns_computed_answer():
    llm = FakeLLM(SPAIN_PLAN, LLMError("down"), LLMError("down"))
    assert Assistant(store, policy, llm).ask("Spain spend?")["answer_source"] == "template"


def test_invalid_plan_is_retried_then_fails_cleanly():
    bad = {"route": "data", "reasoning": "x", "tool_calls": [{"tool": "drop_table"}]}
    llm = FakeLLM(bad, bad)
    with pytest.raises(PlanningFailed):
        Assistant(store, policy, llm).ask("anything")
    assert llm.calls == 2


def test_plan_citing_a_nonexistent_clause_is_rejected():
    llm = FakeLLM({"route": "policy", "reasoning": "x", "policy_clauses": ["99.9"]},
                  {"route": "policy", "reasoning": "x", "policy_clauses": ["5.2"]},
                  {"answer": "Terms are 60 days net (§5.2).", "cited_clauses": ["5.2"]})
    response = Assistant(store, policy, llm).ask("Payment terms?")
    assert [c["id"] for c in response["evidence"]["policy"]] == ["5.2"]


def test_grounding_rejects_fake_clause_and_invoice_ids():
    problems = check_answer("See §12.4 and INV-99999.", [{"id": "D1", "rows": []}], policy.text, "q",
                            [], ["D1"], set(policy.clauses), True)
    assert any("clauses" in p for p in problems) and any("Invoice ids" in p for p in problems)


def test_daily_rates_are_used_with_last_published_rate_on_weekends(tmp_path):
    for name in ("invoices_2025_clean.csv", "vendor_master.csv", "procurement_policy.md"):
        shutil.copy(DATA_DIR / name, tmp_path / name)
    (tmp_path / "ecb_rates_daily.csv").write_text(
        "date,USD,GBP\n2025-01-01,1.00,0.80\n2025-06-06,1.20,0.90\n2025-06-09,1.30,0.95\n")
    daily = DataStore(tmp_path)
    assert daily.fx.info.policy_compliant is True
    assert daily.fx.rate("USD", "2025-06-08") == 1.20  # a Sunday
    assert daily.fx.rate("USD", "2025-06-09") == 1.30


def test_ecb_file_parsing():
    sample = ("Date, USD, JPY, GBP, \n2025-01-03, 1.0299, 162.5, 0.8300, \n"
              "2023-01-03, 1.05, 140, 0.88, \n")
    assert extract_2025(sample) == [{"date": "2025-01-03", "USD": "1.0299", "GBP": "0.8300"}]


def test_provider_clients_parse_their_response_formats():
    anthropic = httpx.MockTransport(lambda r: httpx.Response(200, json={
        "content": [{"type": "tool_use", "input": {"ok": 1}}]}))
    assert AnthropicClient("k", "m", anthropic).complete_json("s", "u", {}) == {"ok": 1}
    ollama = httpx.MockTransport(lambda r: httpx.Response(200, json={
        "message": {"content": json.dumps({"ok": 1})}}))
    assert OllamaClient("http://x", "m", ollama).complete_json("s", "u", {}) == {"ok": 1}
    limited = httpx.MockTransport(lambda r: httpx.Response(429))
    with pytest.raises(LLMError) as err:
        AnthropicClient("k", "m", limited).complete_json("s", "u", {})
    assert err.value.retryable


def test_api_contract_and_errors(monkeypatch):
    client = TestClient(app)
    summary = client.get("/summary").json()
    expected = round(sum(r["eur"] for r in source_rows()), 2)
    assert summary["totals"]["net_eur"] == expected
    assert sum(r["net_eur"] for r in summary["by_currency"]) == pytest.approx(expected)
    assert sum(r["net_eur"] for r in summary["by_vendor_status"]) == pytest.approx(expected)
    assert summary["llm"]["is_stub"] is True
    assert client.post("/ask", json={"question": "   "}).status_code == 422
    assert client.post("/ask", json={"question": "x" * 1001}).status_code == 422

    from app import main
    monkeypatch.setattr(main.assistant, "ask", lambda q: (_ for _ in ()).throw(LLMError("down")))
    outage = TestClient(app).post("/ask", json={"question": "hello"})
    assert outage.status_code == 503 and outage.json()["error"]["retryable"] is True
