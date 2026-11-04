"""GET /summary: computed directly from the data, with no LLM involved."""
from __future__ import annotations

from .data import DataStore
from .tools import control_flags, money, totals


def build_summary(store: DataStore) -> dict:
    df = store.invoices

    def breakdown(column: str, key: str) -> list[dict]:
        rows = [{key: value, "invoice_count": len(g), "native_net": money(g["amount"].sum()),
                 "net_eur": money(g["amount_eur"].sum())} for value, g in df.groupby(column)]
        return sorted(rows, key=lambda r: -r["net_eur"])

    by_status = breakdown("vendor_status", "vendor_status")
    for row in by_status:
        del row["native_net"]  # mixes currencies, so it is meaningless at this level
    return {
        "totals": totals(df),
        "by_currency": breakdown("currency", "currency"),
        "by_vendor_status": by_status,
        "control_flags": control_flags(df),
        "date_range": {"from": df["invoice_date"].min(), "to": df["invoice_date"].max()},
        "fx": vars(store.fx.info),
        "provenance": {"data_version": store.data_version, "source_rows": len(df)},
    }
