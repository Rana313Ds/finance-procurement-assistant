"""Downloads the ECB's 2025 daily reference rates into data/ecb_rates_daily.csv.

Once that file exists the backend uses invoice-date rates, as policy §5.1 requires.
Run: python backend/scripts/fetch_ecb_rates.py   (then restart the backend)
"""
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
OUTPUT = Path(__file__).resolve().parents[2] / "data" / "ecb_rates_daily.csv"


def extract_2025(csv_text: str) -> list[dict]:
    rows = []
    for record in csv.DictReader(io.StringIO(csv_text), skipinitialspace=True):
        date = record["Date"].strip()
        # Include late 2024 so a rate exists for any non-publishing day in early January.
        if "2024-12-15" <= date <= "2025-12-31":
            rows.append({"date": date, "USD": record["USD"].strip(), "GBP": record["GBP"].strip()})
    return sorted(rows, key=lambda r: r["date"])


def main() -> int:
    with urllib.request.urlopen(URL, timeout=30) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    rows = extract_2025(archive.read("eurofxref-hist.csv").decode())
    if not rows:
        print("No 2025 rates found; the file was not written.", file=sys.stderr)
        return 1
    with OUTPUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "USD", "GBP"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} days to {OUTPUT}. Restart the backend to use them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
