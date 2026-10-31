"""Run deterministic LM pilot analysis; source acquisition is a separate step."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
import pandas as pd
from topbottom.analysis import prepare_market, run_analysis


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--crsp", type=Path, help="Local licensed CRSP CIZ monthly CSV; never uploaded")
    parser.add_argument("--factors", type=Path, help="Ken French original monthly FF3 CSV")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if bool(args.crsp) != bool(args.factors):
        parser.error("--crsp and --factors must be supplied together")
    if args.crsp:
        firms = pd.read_csv(args.project/"data/processed/firm_scores.csv")
        meta = prepare_market(args.crsp,args.factors,sorted(firms.ticker.unique()),args.project/"data/private")
        print(f"Prepared {meta['n_tickers']} ticker histories, {meta['n_rows']:,} rows")
    if not args.prepare_only:
        report = run_analysis(args.project)
        print(f"Wrote reports/results.json | firms={report['coverage']['tickers']}, filings={report['coverage']['firm_documents']}, OOS quarters={report['coverage']['oos_periods']}")


if __name__ == "__main__":
    main()
