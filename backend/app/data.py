"""Loads the source files once at startup and derives the fields every query needs.

Every derived value (FX rate, EUR amount) stays on the row next to its source
line number, so any reported figure can be traced back to the CSV (policy §8.2).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DAILY_RATES_FILE = "ecb_rates_daily.csv"


@dataclass(frozen=True)
class FxInfo:
    mode: str  # "daily_ecb" | "annual_average"
    policy_compliant: bool
    note: str


class FxRates:
    """Units of foreign currency per 1 EUR, in the ECB's quoting convention."""

    def __init__(self, data_dir: Path):
        daily = data_dir / DAILY_RATES_FILE
        if daily.exists():
            rates = pd.read_csv(daily, parse_dates=["date"]).set_index("date").sort_index()
            self._daily = rates
            self._annual = None
            self.info = FxInfo(
                "daily_ecb",
                True,
                "EUR figures use the ECB reference rate on each invoice date (§5.1). The ECB "
                "publishes no rate on weekends or TARGET holidays; those dates use the last "
                "published rate.",
            )
        else:
            self._daily = None
            annual = json.loads((data_dir / "fx_annual_avg_2025.json").read_text(encoding="utf-8"))
            self._annual = annual
            self.info = FxInfo(
                "annual_average",
                False,
                "EUR figures are indicative: they use the 2025 annual-average ECB rates "
                f"(USD {annual['USD']}, GBP {annual['GBP']}), not the invoice-date rates §5.1 "
                "requires. Run backend/scripts/fetch_ecb_rates.py to switch to daily rates.",
            )

    def rate(self, currency: str, date: str | None = None) -> float:
        if currency == "EUR":
            return 1.0
        if self._annual is not None:
            return float(self._annual[currency])
        series = self._daily[currency].dropna()
        if date is None:
            return float(series.iloc[-1])
        return float(series.asof(pd.Timestamp(date)))


class DataStore:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.fx = FxRates(data_dir)
        invoice_path = data_dir / "invoices_2025_clean.csv"
        vendor_path = data_dir / "vendor_master.csv"
        invoices = pd.read_csv(invoice_path, keep_default_na=False)
        vendors = pd.read_csv(vendor_path, keep_default_na=False).rename(
            columns={"status": "vendor_status"}
        )
        invoices["source_line"] = range(2, len(invoices) + 2)  # line 1 is the CSV header

        # validate="many_to_one" fails loudly if the vendor master ever gains duplicates.
        df = invoices.merge(
            vendors[["vendor_id", "country", "category", "vendor_status"]],
            on="vendor_id",
            how="left",
            validate="many_to_one",
        )
        if df["vendor_status"].isna().any():
            raise ValueError("Invoice references a vendor missing from the vendor master")

        df["fx_rate"] = [self.fx.rate(c, d) for c, d in zip(df["currency"], df["invoice_date"])]
        # Rounded per invoice so the evidence rows add up exactly to the reported totals.
        df["amount_eur"] = (df["amount"] / df["fx_rate"]).round(2)
        dates = pd.to_datetime(df["invoice_date"])
        df["month"] = dates.dt.strftime("%Y-%m")
        df["quarter"] = "Q" + dates.dt.quarter.astype(str)
        self.invoices = df

        digest = hashlib.sha256()
        fx_file = DAILY_RATES_FILE if self.fx.info.mode == "daily_ecb" else "fx_annual_avg_2025.json"
        for name in ("invoices_2025_clean.csv", "vendor_master.csv", "procurement_policy.md", fx_file):
            digest.update((data_dir / name).read_bytes())
        self.data_version = digest.hexdigest()[:12]
