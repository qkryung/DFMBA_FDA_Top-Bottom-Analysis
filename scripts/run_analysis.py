"""Run deterministic LM analysis; full checkpoints preserve final deliverables."""
from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--scope",choices=["auto","pilot","full"],default="auto")
    parser.add_argument("--reports-dir",type=Path)
    parser.add_argument("--private-dir",type=Path)
    parser.add_argument("--final",action="store_true",help="Publish final full results only after corpus audit/freeze")
    parser.add_argument("--force-market",action="store_true")
    args = parser.parse_args()
    if bool(args.crsp) != bool(args.factors):
        parser.error("--crsp and --factors must be supplied together")
    if args.crsp:
        universe=pd.read_csv(args.project/"data/reference/selected_universe.csv")
        full=args.scope=="full" or (args.scope=="auto" and len(universe)>33)
        tickers=pd.read_csv(args.project/"data/reference/universe_snapshot.csv").ticker.tolist() if full else json.loads((args.project/"configs/research.json").read_text(encoding="utf-8"))["pilot_tickers"]
        private=args.private_dir or args.project/("data/private/full" if full else "data/private")
        identity=json.loads((args.project/"configs/market_identity.json").read_text(encoding="utf-8")) if full else {}
        meta = prepare_market(args.crsp,args.factors,tickers,private,aliases=identity.get("aliases"),unavailable=identity.get("unavailable"),force=args.force_market)
        print(f"Prepared {meta['n_tickers']} ticker histories, {meta['n_rows']:,} rows; cache_reused={meta['cache_reused']}")
    if not args.prepare_only:
        report = run_analysis(args.project,args.scope,args.reports_dir,args.private_dir,args.final)
        print(f"Wrote {report['meta']['status']} | firms={report['coverage']['tickers']}, filings={report['coverage']['firm_documents']}, OOS quarters={report['coverage']['oos_periods']}")


if __name__ == "__main__":
    main()
