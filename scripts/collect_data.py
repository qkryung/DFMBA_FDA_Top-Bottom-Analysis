"""Run from repository root; see --help. Never commits raw documents or credentials."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from topbottom.data import CachedClient, prepare_dictionaries, load_universe, collect_fomc, collect_firms, write_coverage
from topbottom.text import TextScorer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary-zip", type=Path, help="Local authorized LM dictionary zip. Never uploaded.")
    parser.add_argument("--scope", choices=["pilot", "full"], default="pilot")
    parser.add_argument("--only", choices=["all", "fomc", "firms"], default="all")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--tickers", help="Comma-separated explicit ticker selection")
    args = parser.parse_args()
    for folder in ("data/processed", "data/reference", "reports"):
        (ROOT/folder).mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT/"configs/research.json").read_text(encoding="utf-8"))
    if args.start_year: config["start_year"] = args.start_year
    if args.end_year: config["end_year"] = args.end_year
    if args.dictionary_zip: prepare_dictionaries(ROOT, args.dictionary_zip)
    scorer = TextScorer(ROOT)
    client = CachedClient(ROOT, rps=config["sec_requests_per_second"])
    universe = load_universe(ROOT, client)
    universe["current_snapshot_cik"] = universe["cik"]
    universe["cik_mapping_note"] = "Current snapshot CIK"
    for ticker, mapping in config.get("historical_cik_overrides", {}).items():
        if config["end_year"] <= mapping["valid_through_year"]:
            universe.loc[universe.ticker.eq(ticker), "cik"] = mapping["cik"]
            universe.loc[universe.ticker.eq(ticker), "cik_mapping_note"] = mapping["reason"]
    selected = universe
    if args.scope == "pilot": selected = universe[universe.ticker.isin(config["pilot_tickers"])]
    if args.tickers: selected = universe[universe.ticker.isin(args.tickers.split(","))]
    # One issuer's filing is not an independent document for each share class.
    selected = selected.drop_duplicates("cik", keep="first").copy()
    config["universe_basis"] = "Current S&P 500 constituent snapshot and current GICS labels; " + ("selected pilot" if args.scope == "pilot" else "all distinct current issuer CIKs")
    if not args.tickers:
        selected.to_csv(ROOT/"data/reference/selected_universe.csv", index=False)
    if args.only in ("all", "fomc"):
        collect_fomc(ROOT, client, scorer, config["start_year"], config["end_year"])
    if args.only in ("all", "firms"):
        collect_firms(ROOT, client, scorer, selected, config["start_year"], config["end_year"], config["sec_workers"])
    coverage_selection = selected
    if args.tickers and (ROOT/"data/reference/selected_universe.csv").exists():
        coverage_selection = pd.read_csv(ROOT/"data/reference/selected_universe.csv")
    report = write_coverage(ROOT, coverage_selection, config)
    print(json.dumps({k: report[k] for k in ("covered_companies", "firm_documents", "fomc_documents", "failed_acquisitions")}, indent=2))


if __name__ == "__main__": main()
