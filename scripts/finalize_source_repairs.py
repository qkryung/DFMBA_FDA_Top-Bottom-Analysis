"""Apply the final bounded source decisions before score_text and audit_corpus.

Unverified alternative exhibits are terminal exclusions, not claims that no other
source exists. The fixed accession list prevents future retries from selecting a
different slide/table from the same reviewed filing. No return outcome is used.
"""
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from topbottom.data import CachedClient, TextScorer, collect_firms, write_csv_atomic, write_json_atomic, conservative_ir_available_at
from recover_corpus import recover_official_ir_text


def main():
    config = json.loads((ROOT / "configs/research.json").read_text(encoding="utf-8"))
    recovery = json.loads((ROOT / "configs/source_recovery.json").read_text(encoding="utf-8"))
    selected = pd.read_csv(ROOT / "data/reference/selected_universe.csv")
    client = CachedClient(ROOT, rps=min(6, config["sec_requests_per_second"]))
    scorer = TextScorer(ROOT)
    # The reviewed Ford PDF hash uses a second text-layer extractor. All other
    # retained Ford inputs reuse their checkpoints; the broken 2017 PDF is closed.
    collect_firms(ROOT, client, scorer, selected[selected.ticker.eq("F")], config["start_year"], config["end_year"], config["sec_workers"], force=True)
    ge_log = recover_official_ir_text(client, scorer, selected, config["start_year"], config["end_year"], "GE")
    path = ROOT / "data/processed/acquisition_failures.csv"
    failures = pd.read_csv(path)
    rows = []
    for accession, entry in recovery.get("closed_unverified_filings", {}).items():
        rows.append(dict(ticker=entry["ticker"], cik=entry["cik"], accession=accession,
                         filing_date=entry["publication_date"], form=entry.get("form", "8-K"), stage="final_source_review",
                         error_category="reviewed_source_scope_exclusion", error=entry["reason"]))
    if rows:
        failures = pd.concat([failures, pd.DataFrame(rows)], ignore_index=True).drop_duplicates(["ticker", "accession", "stage", "error_category"], keep="last")
        write_csv_atomic(failures, path)
    excluded_path = ROOT / "data/processed/excluded_exhibits.csv"
    exclusions = pd.read_csv(excluded_path)
    terminal_rows = [dict(doc_id=f"sec_{int(e['cik'])}_{a}", ticker=e['ticker'], publication_date=e['publication_date'], source_url=e['source_url'], reason=e['reason'])
                     for a, e in recovery.get("closed_unverified_filings", {}).items()]
    if terminal_rows:
        write_csv_atomic(pd.concat([exclusions, pd.DataFrame(terminal_rows)], ignore_index=True).drop_duplicates(["doc_id", "source_url", "reason"]), excluded_path)
    version_path = ROOT / "reports/official_ir_pdf_version_review.json"
    versions = json.loads(version_path.read_text(encoding="utf-8"))
    known = {r["source_url"] for r in versions["documents"]}
    for row in ge_log:
        if row["status"] != "official_IR_text_recovered_with_SEC_time" or row["source_url"] in known:
            continue
        content = client.get(row["source_url"])
        meta = PdfReader(io.BytesIO(content)).metadata
        timestamps = {k: pd.Timestamp(v).tz_convert("UTC").isoformat() for k, v in (("creation", meta.creation_date), ("modification", meta.modification_date)) if v is not None}
        bound = conservative_ir_available_at(row["sec_acceptance_datetime"], row["publication_date"])
        versions["documents"].append(dict(ticker="GE", publication_date=row["publication_date"], source_url=row["source_url"],
                                         pdf_metadata_utc=timestamps, ir_date_only_available_bound=bound,
                                         version_metadata_not_after_bound=all(pd.Timestamp(v) <= pd.Timestamp(bound) for v in timestamps.values()),
                                         pdf_sha256=hashlib.sha256(content).hexdigest()))
    write_json_atomic(versions, version_path)
    session_path = ROOT / "reports/acquisition_sessions.json"
    sessions = json.loads(session_path.read_text(encoding="utf-8"))
    sessions["sessions"].append(dict(phase="final_bounded_source_repairs", session_started_at=client.started_at,
        ended_at=datetime.now(timezone.utc).isoformat(), http_requests=client.requests_made,
        status_counts=dict(client.http_status_counts), current_global_sec_requests_per_second=1/client.interval,
        count_basis="Exact completed network requests; disk-cache hits excluded"))
    write_json_atomic(sessions, session_path)
    summary_path = ROOT / "reports/source_recovery_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["ge_official_IR_text_recovered"] = sum(r["status"] == "official_IR_text_recovered_with_SEC_time" for r in ge_log)
    summary["terminal_unverified_filings"] = len(recovery.get("closed_unverified_filings", {}))
    summary["final_bounded_source_repairs_finished_at"] = datetime.now(timezone.utc).isoformat()
    summary["terminal_decision_note"] = "Known non-release alternatives excluded after bounded source review; no claim of exhaustive search for every possible issuer source."
    write_json_atomic(summary, summary_path)
    print(json.dumps({"closed_unverified_filings": len(rows), "GE_recovered": summary["ge_official_IR_text_recovered"], "HTTP": dict(client.http_status_counts)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
