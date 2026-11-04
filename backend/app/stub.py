"""STUB planner: keyword rules standing in for the LLM routing step when no model is set.

It is deliberately narrow: anything it does not recognise is declined. Every response
produced this way is labelled as stub output in the API and the UI.
"""
from __future__ import annotations

import re

from .pipeline_types import Plan
from .tools import CheckInvoice, InvoiceFilters, QueryInvoices, RequiredApprover

COUNTRIES = {
    "Germany": r"germany|german",
    "Spain": r"spain|spanish",
    "UK": r"uk|u\.k\.|united kingdom|britain|british|england|english",
    "Netherlands": r"netherlands|dutch|holland",
    "Switzerland": r"switzerland|swiss",
    "Ireland": r"ireland|irish",
    "France": r"france|french",
}
CATEGORIES = {
    "Lab Equipment": r"lab(oratory)? equipment",
    "Lab Consumables": r"lab(oratory)? consumables|consumables|reagents?",
    "Clinical Supplies": r"clinical suppl(y|ies)",
    "IT Services": r"\bit services?|\bit spend|\bi\.t\.|cloud|software|tech(nology)? services",
    "Logistics": r"logistics|shipping|freight",
    "Consulting": r"consult(ing|ancy|ants?)",
    "Marketing Services": r"marketing|printing",
    "Facilities": r"facilit(y|ies)",
    "Travel": r"\btravel",
}
VENDOR_NAMES = ["labtech", "clinsupply", "databridge", "medpack", "helix", "pharmaprint",
                "quanta", "bioreagent", "stellar", "crown"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
QUARTERS = {"q1": ("01-01", "03-31"), "q2": ("04-01", "06-30"),
            "q3": ("07-01", "09-30"), "q4": ("10-01", "12-31")}
GROUPINGS = [("vendor status", "vendor_status"), ("status", "vendor_status"),
             ("cost center", "cost_center"), ("cost centre", "cost_center"),
             ("currency", "currency"), ("country", "country"), ("category", "category"),
             ("quarter", "quarter"), ("month", "month"), ("approver", "approved_by"),
             ("vendor", "vendor")]
POLICY_TOPICS = [
    (r"payment terms|discount", ["5.2"]),
    (r"retain|retention|how long.*(keep|record)", ["8.1"]),
    (r"audit|lineage|sox", ["8.1", "8.2"]),
    (r"emergency|exception", ["9.1"]),
    (r"self.?approv|segregation|approve (my|their) own", ["7.1", "7.2"]),
    (r"new vendor|due diligence", ["4.2"]),
    (r"bank details|master data", ["4.3"]),
    (r"reporting currency|exchange rate|\bfx\b|convert", ["5.1"]),
    (r"credit note|negative", ["6.1"]),
    (r"inactive|on.?hold", ["4.1"]),
    (r"maverick|purchase order|\bpo\b|blanket", ["2.1", "2.2", "2.3"]),
    (r"scope|clinical trial", ["1"]),
    (r"threshold|approv", ["3", "3.1"]),
]
UNAVAILABLE = (
    (r"been paid|was paid|payment status|overdue|outstanding", "payment status"),
    (r"\b20(1\d|2[0-46-9])\b|forecast|budget", "anything other than 2025 invoices"),
    (r"requester|requested by|who requested", "requesters"),
)
DATA_INTENT = (r"\b(top|total|spend|spent|how much|how many|list|show|which|breakdown|largest|"
               r"biggest|highest|smallest|lowest|most|fewest|average|avg|mean|count|number of|by|per|"
               r"monthly|quarterly)\b")
FILTER_WORDS = r"(missing|without|no) (a )?(po|purchase order|approver|approval)|credit note|inactive|on.?hold"
INVOICE_SUPERLATIVE = re.compile(
    r"\b(largest|biggest|highest|most expensive|smallest|lowest|cheapest)\s+(\d+\s+)?"
    r"(single\s+|individual\s+)?(invoices?|bills?|credit notes?)")
VENDOR_RANKING = re.compile(
    r"\b(which|what)\s+(of (our|the) )?(vendors?|suppliers?)\b|"
    r"\b(top|biggest|largest|main|highest|most|smallest|lowest|fewest)\b[^?]*\b(vendors?|suppliers?)\b|"
    r"\b(vendors?|suppliers?)\b[^?]*\b(most|highest|largest|biggest|fewest|lowest|least)\b|"
    r"\b(vendors?|suppliers?) (ranking|ranked)\b")
ASCENDING = r"\b(smallest|lowest|cheapest|fewest|least|bottom)\b"
ABOVE = r"\b(above|over|more than|greater than|exceeding|exceeds?|in excess of)\s*$"
BELOW = r"\b(below|under|less than|lower than)\s*$"


def plan(question: str) -> Plan:
    q = question.lower()

    for pattern, missing in UNAVAILABLE:
        if re.search(pattern, q):
            return Plan(route="none", reasoning=f"The data does not include {missing}.")

    invoice = re.search(r"inv-\d+", q)
    if invoice:
        return Plan(route="both",
                    reasoning="This asks about one invoice, so I need its record and the control rules.",
                    tool_calls=[CheckInvoice(invoice_number=invoice.group())],
                    policy_clauses=["2.1", "2.2", "3", "3.1", "4.1", "7.1"])

    amount = _amount(q)
    if amount and "approv" in q:
        return Plan(route="policy",
                    reasoning="Approval authority is set by the policy's thresholds; no invoice data is needed.",
                    tool_calls=[RequiredApprover(amount=amount[0], currency=amount[1])],
                    policy_clauses=["3", "3.1", "7.1", "7.2"])

    clauses = next((c for pattern, c in POLICY_TOPICS if re.search(pattern, q)), [])
    if re.search(DATA_INTENT, q) and (_mentions_spend(q) or re.search(FILTER_WORDS, q)):
        return _data_plan(q)
    if clauses:
        return Plan(route="policy", reasoning="This is a question about the policy's rules.",
                    policy_clauses=clauses)
    return Plan(route="none",
                reasoning="The stub planner recognises only a fixed set of question patterns, and "
                          "this is not one of them.")


def _data_plan(q: str) -> Plan:
    filters, clauses = _filters(q)
    order = "asc" if re.search(ASCENDING, q) else "desc"
    top = re.search(r"\b(?:top|bottom|first)\s+(\d+)", q)
    top_n = int(top.group(1)) if top else None
    sort_by = ("invoice_count" if re.search(r"(most|fewest|least|number of|count of|how many) invoices", q)
               else "net_eur")

    group_by = None
    match = re.search(r"\b(?:by|per|each|for every)\b(.*)", q)
    if match:
        group_by = next((g for word, g in GROUPINGS if re.search(rf"\b{word}", match.group(1))), None)
    if not group_by and re.search(r"\bmonthly\b|month by month|each month", q):
        group_by = "month"
    if not group_by and re.search(r"\bquarterly\b|each quarter", q):
        group_by = "quarter"

    superlative = INVOICE_SUPERLATIVE.search(q)
    if superlative and not group_by:
        # Individual invoices, not a grouped ranking.
        count = superlative.group(2)
        plural_noun = superlative.group(4).endswith("s")
        top_n = int(count) if count else top_n or (5 if plural_noun else 1)
        if "credit note" in superlative.group(4):
            filters = filters.model_copy(update={"is_credit_note": True})
            order = "asc" if order == "desc" else "desc"  # "largest" credit note is the most negative
        elif filters.is_credit_note is None:
            filters = filters.model_copy(update={"is_credit_note": False})
    elif not group_by and (top_n or (VENDOR_RANKING.search(q) and not filters.vendor_name_contains
                                     and not re.search(r"\b(which|what|list|show)\s+(\w+\s+){0,2}invoices\b", q))):
        group_by = "vendor"
        singular = re.search(r"\b(which|what)\s+(vendor|supplier)\b(?!s)|"
                             r"\b(top|biggest|largest|main|highest|smallest|lowest)\s+(vendor|supplier)\b(?!s)", q)
        if not top_n and singular and re.search(
                r"\b(most|biggest|largest|highest|top|main|smallest|lowest|fewest|least)\b", q):
            top_n = 1

    call = QueryInvoices(filters=filters, group_by=group_by, sort_by=sort_by, order=order, top_n=top_n)
    if clauses:
        return Plan(route="both", tool_calls=[call], policy_clauses=clauses,
                    reasoning="This needs invoice figures and the policy rule behind that control.")
    return Plan(route="data", tool_calls=[call],
                reasoning="This is a calculation over invoice and vendor data; no policy rule is needed.")


def _filters(q: str) -> tuple[InvoiceFilters, list[str]]:
    values: dict = {}
    clauses: list[str] = []
    countries = [c for c, pattern in COUNTRIES.items() if re.search(rf"\b(?:{pattern})\b", q)]
    if countries:
        values["country"] = countries
    vendor = next((v for v in VENDOR_NAMES if v in q), None)
    if vendor:
        values["vendor_name_contains"] = vendor
    else:  # A vendor name already pins the category, and "Crown Travel" is not a travel query.
        category = next((c for c, pattern in CATEGORIES.items() if re.search(pattern, q)), None)
        if category:
            values["category"] = category
    currencies = [c.upper() for c in ("eur", "gbp", "usd") if re.search(rf"\b{c}\b", q)]
    if currencies:
        values["currency"] = currencies
    cost_center = re.search(r"cc-[a-z]+-\d+", q)
    if cost_center:
        values["cost_center"] = cost_center.group()

    statuses = []
    if re.search(r"non.?active|not active", q):
        statuses = ["INACTIVE", "ON_HOLD"]
    else:
        if "inactive" in q: statuses.append("INACTIVE")
        if re.search(r"on.?hold", q): statuses.append("ON_HOLD")
    if statuses:
        values["vendor_status"] = statuses
        clauses.append("4.1")
    if re.search(r"(missing|without|no) (a )?(po|purchase order)", q):
        values.update(has_po=False, min_amount_eur=1000)
        clauses += ["2.1", "2.2"]
    if re.search(r"(missing|without|no) (an )?(approver|approval)", q):
        values["has_approver"] = False
        clauses.append("3.1")
    if "credit note" in q:
        values["is_credit_note"] = True
        clauses.append("6.1")

    quarter = next((k for k in QUARTERS if re.search(rf"\b{k}\b", q)), None)
    if quarter:
        start, end = QUARTERS[quarter]
        values.update(date_from=f"2025-{start}", date_to=f"2025-{end}")
    month = next((i for i, m in enumerate(MONTHS, 1) if re.search(rf"\b{m}\b", q)), None)
    if month and not quarter:
        last_day = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
        values.update(date_from=f"2025-{month:02d}-01", date_to=f"2025-{month:02d}-{last_day}")
    return InvoiceFilters(**values), clauses


def _mentions_spend(q: str) -> bool:
    return bool(re.search(r"spend|spent|invoice|bill|vendor|supplier|how much|top \d|cost", q))


# Numbers that are identifiers or dates, not amounts: years, quarters, invoice/PO/cost-center ids.
_NOT_AMOUNTS = re.compile(r"\b(?:inv|po|cc)-[\w-]*\d+\b|\bq[1-4]\b|§\s*[\d.]+|\b\d{4}-\d{2}-\d{2}\b|"
                          r"(?<![€£$\d,.])(?<!eur )(?<!gbp )(?<!usd )\b20[0-3]\d\b(?!\s*(?:eur|gbp|usd|euros?|k\b|,\d))")
_CURRENCY = {"€": "EUR", "£": "GBP", "$": "USD", "euro": "EUR", "euros": "EUR", "pound": "GBP",
             "pounds": "GBP", "dollar": "USD", "dollars": "USD"}


def _amount(q: str) -> tuple[float, str] | None:
    cleaned = _NOT_AMOUNTS.sub(" ", q)
    pattern = (r"(eur|gbp|usd|€|£|\$)?\s*(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\b\s*"
               r"(eur|gbp|usd|euros?|pounds?|dollars?)?")
    for match in re.finditer(pattern, cleaned):
        value = float(match.group(2).replace(",", ""))
        value *= {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}.get(match.group(3) or "", 1)
        symbol = match.group(1) or match.group(4) or "eur"
        currency = _CURRENCY.get(symbol, symbol[:3].upper())
        # "above 250k" means strictly more than 250,000, which can change the approval band.
        before = cleaned[: match.start()]
        if re.search(ABOVE, before):
            value += 0.01
        elif re.search(BELOW, before):
            value -= 0.01
        return round(value, 2), currency
    return None
