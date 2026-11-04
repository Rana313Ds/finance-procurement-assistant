"""The only ways the assistant can reach data: typed, read-only, allow-listed tools.

We use tools rather than text-to-SQL because every figure must be reproducible and
explainable. The LLM picks the parameters; this code does all of the arithmetic.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from .data import DataStore
from .policy import Policy

GROUP_COLUMNS = {
    "vendor": "vendor_name",
    "country": "country",
    "vendor_status": "vendor_status",
    "currency": "currency",
    "cost_center": "cost_center",
    "category": "category",
    "month": "month",
    "quarter": "quarter",
    "approved_by": "approved_by",
    "description": "description",
}
ROW_COLUMNS = [
    "invoice_number", "invoice_date", "vendor_name", "country", "vendor_status", "description",
    "amount", "currency", "fx_rate", "amount_eur", "cost_center", "po_number", "approved_by",
    "source_line",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvoiceFilters(Strict):
    invoice_numbers: list[str] | None = None
    vendor_name_contains: str | None = None
    vendor_status: list[Literal["ACTIVE", "INACTIVE", "ON_HOLD"]] | None = None
    country: list[str] | None = None
    category: str | None = None
    currency: list[Literal["EUR", "GBP", "USD"]] | None = None
    cost_center: str | None = None
    approved_by: str | None = None
    description_contains: str | None = None
    date_from: str | None = Field(None, description="Inclusive, YYYY-MM-DD")
    date_to: str | None = Field(None, description="Inclusive, YYYY-MM-DD")
    has_po: bool | None = None
    has_approver: bool | None = None
    is_credit_note: bool | None = None
    min_amount_eur: float | None = None
    max_amount_eur: float | None = None


class QueryInvoices(Strict):
    tool: Literal["query_invoices"] = "query_invoices"
    filters: InvoiceFilters = Field(default_factory=InvoiceFilters)
    group_by: Literal[tuple(GROUP_COLUMNS)] | None = None  # type: ignore[valid-type]
    sort_by: Literal["net_eur", "invoice_count"] = "net_eur"
    order: Literal["desc", "asc"] = Field("desc", description="desc = largest first, asc = smallest first")
    top_n: int | None = Field(None, ge=1, le=140)


class CheckInvoice(Strict):
    tool: Literal["check_invoice"] = "check_invoice"
    invoice_number: str


class RequiredApprover(Strict):
    tool: Literal["required_approver"] = "required_approver"
    amount: float
    currency: Literal["EUR", "GBP", "USD"] = "EUR"
    invoice_date: str | None = None


ToolCall = Annotated[
    Union[QueryInvoices, CheckInvoice, RequiredApprover], Field(discriminator="tool")
]


class Tools:
    def __init__(self, store: DataStore, policy: Policy):
        self.store = store
        self.policy = policy

    def run(self, call: QueryInvoices | CheckInvoice | RequiredApprover, result_id: str) -> dict:
        if isinstance(call, QueryInvoices):
            result = self._query_invoices(call)
        elif isinstance(call, CheckInvoice):
            result = self._check_invoice(call)
        else:
            result = self._required_approver(call)
        return {"id": result_id, "tool": call.tool, "parameters": call.model_dump(exclude_none=True),
                **result}

    # ---- query_invoices -------------------------------------------------------------

    def _filter(self, f: InvoiceFilters) -> pd.DataFrame:
        df = self.store.invoices
        mask = pd.Series(True, index=df.index)

        def contains(column: str, needle: str) -> pd.Series:
            return df[column].str.contains(needle, case=False, regex=False)

        def is_in(column: str, values: list[str]) -> pd.Series:
            return df[column].str.casefold().isin([v.casefold() for v in values])

        if f.invoice_numbers: mask &= is_in("invoice_number", f.invoice_numbers)
        if f.vendor_name_contains: mask &= contains("vendor_name", f.vendor_name_contains)
        if f.vendor_status: mask &= df["vendor_status"].isin(f.vendor_status)
        if f.country: mask &= is_in("country", f.country)
        if f.category: mask &= contains("category", f.category)
        if f.currency: mask &= df["currency"].isin(f.currency)
        if f.cost_center: mask &= contains("cost_center", f.cost_center)
        if f.approved_by: mask &= contains("approved_by", f.approved_by)
        if f.description_contains: mask &= contains("description", f.description_contains)
        if f.date_from: mask &= df["invoice_date"] >= f.date_from
        if f.date_to: mask &= df["invoice_date"] <= f.date_to
        if f.has_po is not None: mask &= (df["po_number"] != "") == f.has_po
        if f.has_approver is not None: mask &= (df["approved_by"] != "") == f.has_approver
        if f.is_credit_note is not None: mask &= (df["amount"] < 0) == f.is_credit_note
        if f.min_amount_eur is not None: mask &= df["amount_eur"] >= f.min_amount_eur
        if f.max_amount_eur is not None: mask &= df["amount_eur"] <= f.max_amount_eur
        return df[mask]

    def _query_invoices(self, call: QueryInvoices) -> dict:
        matched = self._filter(call.filters)
        result = {"totals": totals(matched), "control_flags": control_flags(matched),
                  "groups": None, "rows_scope": "all matching invoices"}
        rows = matched
        if call.group_by:
            column = GROUP_COLUMNS[call.group_by]
            groups = [
                {"key": key or "(blank)", "invoice_count": len(g),
                 "net_eur": money(g["amount_eur"].sum()),
                 "credit_notes_eur": money(g.loc[g["amount"] < 0, "amount_eur"].sum())}
                for key, g in matched.groupby(column)
            ]
            sign = -1 if call.order == "desc" else 1
            groups.sort(key=lambda g: (sign * g[call.sort_by], g["key"]))
            if call.top_n:
                groups = groups[: call.top_n]
                keys = {"" if g["key"] == "(blank)" else g["key"] for g in groups}
                rows = matched[matched[column].isin(keys)]
                result["rows_scope"] = f"invoices in the top {len(groups)} groups only"
            result["groups"] = groups
        elif call.top_n:
            rows = matched.sort_values("amount_eur", ascending=call.order == "asc").head(call.top_n)
            which = "largest" if call.order == "desc" else "smallest"
            result["rows_scope"] = f"{which} {len(rows)} of {len(matched)} matching invoices"
        result["rows"] = to_rows(rows.sort_values("source_line"))
        return result

    # ---- check_invoice --------------------------------------------------------------

    def _check_invoice(self, call: CheckInvoice) -> dict:
        df = self.store.invoices
        match = df[df["invoice_number"].str.casefold() == call.invoice_number.strip().casefold()]
        if match.empty:
            return {"found": False, "rows": [], "checks": []}
        row = match.iloc[0]
        return {"found": True, "rows": to_rows(match), "checks": self._control_checks(row)}

    def _control_checks(self, row: pd.Series) -> list[dict]:
        band = self.policy.approver_for(row["amount_eur"])
        active = row["vendor_status"] == "ACTIVE"
        has_po = row["po_number"] != ""
        needs_po = abs(row["amount_eur"]) >= 1000
        approver = row["approved_by"]
        checks = [
            check("Vendor status", "pass" if active else "fail", "4.1",
                  f"Vendor is {row['vendor_status']}"
                  + ("." if active else "; escalate to Procurement Excellence before processing.")),
            check("Approver recorded", "pass" if approver else "fail", "3.1",
                  f"Approved by {approver}." if approver
                  else "No approver record; the invoice must be held and may not be paid."),
            check("Purchase order", "pass" if has_po or not needs_po else "fail", "2.2",
                  f"PO {row['po_number']}." if has_po else
                  ("No PO at or above the EUR 1,000 threshold; flag as maverick spend unless "
                   "the Exception Register (§9.1) covers it, which this data cannot show."
                   if needs_po else "No PO, and below the EUR 1,000 threshold.")),
            check("Approver authority", "cannot_verify", "3",
                  f"Requires {band.approver}. The data has no role directory, so we cannot "
                  f"confirm whether {approver or 'any approver'} holds that authority."),
            check("Segregation of duties", "cannot_verify", "7.1",
                  "The data has no requester field, so self-approval cannot be tested."),
        ]
        if row["amount"] < 0:
            checks.append(check("Credit note matching", "cannot_verify", "6.1",
                                "The data does not link credit notes to original invoices."))
        return checks

    # ---- required_approver ----------------------------------------------------------

    def _required_approver(self, call: RequiredApprover) -> dict:
        rate = self.store.fx.rate(call.currency, call.invoice_date)
        amount_eur = money(call.amount / rate)
        band = self.policy.approver_for(amount_eur)
        return {"amount": call.amount, "currency": call.currency, "fx_rate": rate,
                "amount_eur": amount_eur, "band_eur": band.label, "required_approver": band.approver}


def check(name: str, status: str, clause: str, detail: str) -> dict:
    return {"check": name, "status": status, "clause": clause, "detail": detail}


def money(value: float) -> float:
    return round(float(value), 2)


def totals(df: pd.DataFrame) -> dict:
    credit = df[df["amount"] < 0]
    return {
        "invoice_count": len(df),
        "net_eur": money(df["amount_eur"].sum()),
        "gross_eur": money(df.loc[df["amount"] >= 0, "amount_eur"].sum()),
        "credit_notes_eur": money(credit["amount_eur"].sum()),
        "credit_note_count": len(credit),
        "average_eur": money(df["amount_eur"].sum() / len(df)) if len(df) else 0.0,
        "native_net": {c: money(g["amount"].sum()) for c, g in df.groupby("currency")},
    }


def control_flags(df: pd.DataFrame) -> dict:
    no_po = df[(df["po_number"] == "") & (df["amount_eur"].abs() >= 1000)]
    no_approver = df[df["approved_by"] == ""]
    non_active = df[df["vendor_status"] != "ACTIVE"]
    return {
        "missing_po_count": len(no_po), "missing_po_eur": money(no_po["amount_eur"].sum()),
        "missing_approver_count": len(no_approver),
        "missing_approver_eur": money(no_approver["amount_eur"].sum()),
        "non_active_vendor_count": len(non_active),
        "non_active_vendor_eur": money(non_active["amount_eur"].sum()),
    }


def to_rows(df: pd.DataFrame) -> list[dict]:
    return df[ROW_COLUMNS].to_dict(orient="records")
