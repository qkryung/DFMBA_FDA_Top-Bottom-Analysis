"""Recover reviewed source exceptions and narrowly verified metadata mistakes.

Run after full collection with SEC_USER_AGENT set. No current-issuer or security
history is inferred. Missing quarters are an inspection filter, not a target to
fill with unrelated disclosures. All network calls share one rate-limited client.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import io
from pathlib import Path
import re
import sys
import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from topbottom.data import (CachedClient, TextScorer, collect_firms, filing_rows,
                            extract_text, write_csv_atomic, write_json_atomic,
                            source_recovery, classify_failure, exclusion_reason,
                            earnings_exhibit, save_document, points_to_shareholder_letter,
                            conservative_ir_available_at)

ITEM_202_HEADING = re.compile(r"Item\s*2\s*\.\s*02\s*[.:-]?\s*Results\s+of\s+Operations", re.I)


def recover_official_ir_text(client, scorer, selected, start, end, ticker):
    """Replace image-only SEC release extraction with the same official IR release.

    Keep original SEC acceptance separately. Date-only IR text becomes available
    after the IR release's New York calendar day, or SEC acceptance if later.
    """
    source_list = ROOT / f"data/reference/{ticker.lower()}_ir_sources.csv"
    if not source_list.exists():
        return []
    company = selected[selected.ticker.eq(ticker)].iloc[0].to_dict()
    cik = int(company["cik"])
    filings = filing_rows(client, cik, start, end)
    ledger = json.loads((ROOT / "reports/corpus_repairs_full.json").read_text(encoding="utf-8"))
    reviewed_accessions = {row["doc_id"].rsplit("_", 1)[-1] for row in ledger["repairs"]
                           if row["ticker"] == ticker and ("image" in row["reason"].lower() or ticker == "LHX" and "letter" in row["reason"].lower())}
    reviewed_accessions.update(source_recovery().get("official_ir_reviewed_accessions", {}).get(ticker, []))
    path = ROOT / "data/processed/firm_scores.csv"
    firms = pd.read_csv(path, low_memory=False)
    records, log = [], []
    for source in pd.read_csv(source_list).to_dict("records"):
        candidates = [f for f in filings if f["accessionNumber"] in reviewed_accessions
                      and 0 <= (pd.Timestamp(f["filingDate"])-pd.Timestamp(source["publication_date"])).days <= 3]
        candidates.sort(key=lambda f: f.get("acceptanceDateTime", f["filingDate"]))
        if not candidates:
            log.append(dict(source, status="no_matching_SEC_filing"))
            continue
        filing = candidates[0]
        accession = filing["accessionNumber"]
        try:
            content = client.get(source["source_url"])
            pdf = content.lstrip().startswith(b"%PDF")
            if pdf:
                text = extract_text(content)
            else:
                body = BeautifulSoup(content, "lxml").select_one(".wd_body")
                if body is None:
                    raise ValueError("Official IR article body selector absent")
                text = extract_text(str(body).encode("utf-8"))
            issuer_heading = {"EOG": r"EOG Resources", "GE": r"\bGE\b|General Electric", "LHX": r"L3Harris"}[ticker]
            if not re.search(issuer_heading, text[:5000], re.I) or not re.search(r"quarter|full.year|\b[1-4]Q\b", text[:5000], re.I):
                raise ValueError("Official IR release lacks expected issuer/earnings heading")
            from topbottom.data import has_substantive_narrative
            if not has_substantive_narrative(text):
                raise ValueError("Official IR release has no substantive narrative")
            published = filing.get("acceptanceDateTime")
            if not published:
                raise ValueError("Matched SEC acceptance timestamp absent")
            available = conservative_ir_available_at(published, source["publication_date"])
            pdf_metadata = {}
            if pdf:
                from pypdf import PdfReader
                metadata = PdfReader(io.BytesIO(content)).metadata
                for key, value in (("pdf_creation_datetime", metadata.creation_date), ("pdf_modification_datetime", metadata.modification_date)):
                    if value is not None:
                        timestamp = pd.Timestamp(value)
                        if timestamp.tzinfo is None:
                            raise ValueError("PDF metadata timezone absent; cannot resolve historical version timing")
                        if timestamp > pd.Timestamp(available):
                            raise ValueError("PDF metadata postdates conservative IR availability; later revised version excluded")
                        pdf_metadata[key] = timestamp.tz_convert("UTC").isoformat()
            sec_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.html"
            row = dict(doc_id=f"sec_{cik}_{accession}", ticker=ticker, company=company["company"], sector=company["sector"],
                       cik=cik, issuer_id=int(company["issuer_id"]), accession=accession,
                       publication_date=filing["filingDate"], published_at=available, sec_acceptance_at=published,
                       document_type="official_IR_earnings_release_PDF_matched_to_SEC_filing" if pdf else "official_IR_earnings_release_matched_to_SEC_filing",
                       source_url=source["source_url"], matched_SEC_source_url=sec_url,
                       official_IR_source_url=source["source_url"], official_IR_release_date=source["publication_date"],
                       sec_item_tags=filing.get("items", ""),
                       publication_time_basis="Max of matched SEC acceptance and midnight America/New_York after date-only official IR release; PDF metadata is a version check, not proof of public release time",
                       text_scope="Official issuer investor-relations Press Release PDF text layer; replaces image-only SEC release without OCR. Whole press release including financial statements retained." if pdf else "Official issuer investor-relations .wd_body article text; replaces image-only SEC release narrative without OCR. Article financial statements retained; website navigation excluded.")
            if ticker == "LHX":
                row["document_type"] = "official_IR_earnings_investor_letter_PDF_matched_to_SEC_filing"
                row["text_scope"] = "Official issuer earnings Investor Letter PDF text layer; same-day original PDF verified, includes CEO narrative and accompanying financial statements. Replaces results-availability notice; later revised PDFs excluded."
            row.update(pdf_metadata)
            records.append(save_document(ROOT, row, text, scorer))
            log.append(dict(source, status="official_IR_text_recovered_with_SEC_time", doc_id=row["doc_id"], sec_acceptance_datetime=published, available_at=available, matched_SEC_source_url=sec_url))
        except Exception as error:
            log.append(dict(source, status="official_IR_recovery_failed", error_category=classify_failure(error), error=str(error)))
    if records:
        firms = pd.concat([firms, pd.DataFrame(records)], ignore_index=True).drop_duplicates(["ticker", "doc_id"], keep="last")
        write_csv_atomic(firms.sort_values(["ticker", "published_at"]), path)
    write_csv_atomic(pd.DataFrame(log), ROOT / f"data/processed/{ticker.lower()}_source_recovery.csv")
    print(f"{ticker} official IR narratives recovered: {len(records)}", flush=True)
    return log


def recover_echostar_exhibits(client, scorer, selected, start, end):
    """Bounded exception: standalone consolidated EchoStar releases attached to 10-K/Q.

    Official IR publication dates define candidates. HSS filings can carry the
    parent's release, but HSS-only results and whole reports are never scored.
    Direct IR access was unavailable; no access restriction is bypassed.
    """
    source_list = ROOT / "data/reference/echostar_ir_sources.csv"
    if not source_list.exists():
        return []
    sources = pd.read_csv(source_list).to_dict("records")
    primary_path = ROOT / "data/processed/firm_scores.csv"
    firms = pd.read_csv(primary_path, low_memory=False)
    company = selected[selected.ticker.eq("ECHO")].iloc[0].to_dict()
    existing_dates = set(firms.loc[firms.ticker.eq("ECHO"), "publication_date"])
    filings = []
    for cik in (1415404, 1533758):
        for filing in filing_rows(client, cik, start, end, include_forms=("10-K", "10-Q")):
            if filing.get("form") in ("10-K", "10-Q"):
                filings.append((cik, filing))
    records, log = [], []
    for source in sources:
        release_date = source["publication_date"]
        if release_date in existing_dates:
            log.append(dict(source, status="existing_SEC_release_retained"))
            continue
        candidates = [(cik, f) for cik, f in filings
                      if 0 <= (pd.Timestamp(f["filingDate"])-pd.Timestamp(release_date)).days <= 3]
        candidates.sort(key=lambda item: item[1].get("acceptanceDateTime", item[1]["filingDate"]))
        found = False
        for cik, filing in candidates:
            accession = filing["accessionNumber"]
            filing = dict(filing, required_issuer_heading=r"EchoStar(?:\s+Corporation)?\s+(?:Reports|Announces).{0,150}(?:Results|Earnings)")
            try:
                url, content = earnings_exhibit(client, cik, filing)
                published = filing.get("acceptanceDateTime")
                if not published:
                    continue
                row = dict(doc_id=f"sec_{cik}_{accession}", ticker="ECHO", company=company["company"],
                           sector=company["sector"], cik=cik, issuer_id=int(company["issuer_id"]),
                           published_at=published, publication_date=filing["filingDate"],
                           document_type="SEC_10KQ_EX99_reviewed_consolidated_parent_earnings_release",
                           source_url=url, accession=accession, sec_item_tags="", official_IR_release_date=release_date,
                           official_IR_source_url=source["source_url"],
                           publication_time_basis="Actual SEC acceptance UTC; conservative when issuer IR release preceded filing",
                           text_scope="Standalone EX99 consolidated EchoStar earnings release attached to parent or HSS 10-K/10-Q; whole periodic report and HSS-only results excluded")
                records.append(save_document(ROOT, row, extract_text(content), scorer))
                log.append(dict(source, status="recovered_SEC_standalone_release_exhibit", sec_source_url=url,
                                sec_acceptance_datetime=published, reporting_parent="EchoStar", archive_filer_cik=cik))
                found = True
                break
            except Exception as error:
                log.append(dict(source, status="candidate_exhibit_unavailable", accession=accession,
                                archive_filer_cik=cik, error_category=classify_failure(error)))
        if not found:
            log.append(dict(source, status="IR_direct_access_unavailable_and_no_qualifying_SEC_exhibit"))
    if records:
        firms = pd.concat([firms, pd.DataFrame(records)], ignore_index=True).drop_duplicates(["ticker", "doc_id"], keep="last")
        write_csv_atomic(firms.sort_values(["ticker", "published_at"]), primary_path)
    write_csv_atomic(pd.DataFrame(log), ROOT / "data/processed/echostar_source_recovery.csv")
    print(f"EchoStar standalone periodic-report exhibits recovered: {len(records)}", flush=True)
    return log


def verify_missing_quarter_filings(client, company, gaps, start, end):
    checked, verified = [], []
    ticker, cik = company["ticker"], int(company["cik"])
    if not gaps:
        return checked, verified
    try:
        filings = filing_rows(client, cik, start, end, include_unlabeled=True)
    except Exception as error:
        return [{"ticker": ticker, "cik": cik, "status": "metadata_error", "error_category": classify_failure(error), "error": str(error)}], []
    for filing in filings:
        if filing.get("form") != "8-K" or str(pd.Period(filing["filingDate"], freq="Q")) not in gaps:
            continue
        items = str(filing.get("items", ""))
        if "2.02" in items or not ("2.01" in items or items.replace(" ", "") == "9.01"):
            continue
        accession = filing["accessionNumber"]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{filing['primaryDocument']}"
        row = {"ticker": ticker, "cik": cik, "accession": accession,
               "filing_date": filing["filingDate"], "metadata_item_tags": items,
               "primary_document_url": url, "status": "no_Item2.02_heading"}
        try:
            text = extract_text(client.get(url))
            if ITEM_202_HEADING.search(text):
                row["status"] = "verified_Item2.02_heading"
                verified.append(row.copy())
        except Exception as error:
            row.update(status="source_error", error_category=classify_failure(error), error=str(error))
        checked.append(row)
    return checked, verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-metadata-scan", action="store_true")
    args = parser.parse_args()
    status_path = ROOT / "data/processed/issuer_collection_status.csv"
    statuses = pd.read_csv(status_path)
    if statuses.status.isin(["pending", "running"]).any():
        raise RuntimeError("Initial issuer collection is still running; finish it before starting the single-client recovery pass.")
    config_path = ROOT / "configs/research.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    selected = pd.read_csv(ROOT / "data/reference/selected_universe.csv")
    metrics_path = ROOT / "reports/acquisition_http_metrics.json"
    prior_metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    starting_rps = min(config["sec_requests_per_second"], prior_metrics.get("current_global_sec_requests_per_second", config["sec_requests_per_second"]))
    session_path = ROOT / "reports/acquisition_sessions.json"
    sessions = json.loads(session_path.read_text(encoding="utf-8")) if session_path.exists() else {"sessions": []}
    if prior_metrics and not any(s.get("session_started_at") == prior_metrics["session_started_at"] for s in sessions["sessions"]):
        sessions["sessions"].append(dict(prior_metrics, phase="initial_full_collection_after_cooldown", metrics_observed_through=prior_metrics["updated_at"]))
        write_json_atomic(sessions, session_path)
    client = CachedClient(ROOT, rps=starting_rps)
    scorer = TextScorer(ROOT)
    start, end = config["start_year"], config["end_year"]
    recovery = source_recovery()
    queue = set(recovery.get("issuer_repair_queue", []))
    # New source-quality rules may identify a notification instead of the actual
    # earnings letter. Reinspect that issuer so another exhibit can be selected.
    primary = pd.read_csv(ROOT / "data/processed/firm_scores.csv")
    rejected_inputs = []
    for row in primary.to_dict("records"):
        text = (ROOT / "data/raw/text" / (row["doc_id"]+".txt")).read_text(encoding="utf-8")
        reason = exclusion_reason(text, row["source_url"])
        if points_to_shareholder_letter(text):
            queue.add(row["ticker"])
        if not reason and (row["word_count"] < 100 or row["sentence_count"] <= 2):
            reason = "Insufficient analyzable narrative after boilerplate exclusion; inspect alternative exhibit"
        if reason:
            queue.add(row["ticker"])
            rejected_inputs.append({k: row[k] for k in ("doc_id", "ticker", "publication_date", "source_url")} | {"reason": reason})
    # PDF/foreign-filer fallback is relevant to zero-document issuers and prior
    # unsupported-exhibit candidates; successful per-document caches are reused.
    failure_path = ROOT / "data/processed/acquisition_failures.csv"
    failures = pd.read_csv(failure_path)
    if len(failures):
        queue.update(failures.loc[failures.error_category.eq("no_qualifying_earnings_exhibit"), "ticker"])
    queue.update(statuses.loc[statuses.documents.eq(0), "ticker"])
    queue = sorted(queue)
    if rejected_inputs:
        ledger_path = ROOT / "data/processed/excluded_exhibits.csv"
        old_ledger = pd.read_csv(ledger_path) if ledger_path.exists() else pd.DataFrame()
        ledger = pd.concat([old_ledger, pd.DataFrame(rejected_inputs)], ignore_index=True).drop_duplicates(["doc_id", "source_url", "reason"])
        write_csv_atomic(ledger, ledger_path)
    print(f"Reviewed source/history recovery: {len(queue)} issuers", flush=True)
    if queue:
        collect_firms(ROOT, client, scorer, selected[selected.ticker.isin(queue)], start, end, config["sec_workers"], force=True)
    checked, verified = [], []
    if not args.skip_metadata_scan:
        firms = pd.read_csv(ROOT / "data/processed/firm_scores.csv")
        available = firms.assign(quarter=pd.to_datetime(firms.publication_date).dt.to_period("Q").astype(str)).groupby("ticker").quarter.agg(set).to_dict()
        periods = set(pd.period_range(f"{start}Q1", f"{end}Q4", freq="Q").astype(str))
        targets = [(company, periods-available.get(company["ticker"], set())) for company in selected.to_dict("records")]
        targets = [(company, gaps) for company, gaps in targets if gaps]
        print(f"Missing-quarter metadata inspection: {len(targets)} issuers", flush=True)
        with ThreadPoolExecutor(max_workers=config["sec_workers"]) as executor:
            futures = [executor.submit(verify_missing_quarter_filings, client, company, gaps, start, end) for company, gaps in targets]
            for index, future in enumerate(as_completed(futures), 1):
                inspected, matches = future.result()
                checked.extend(inspected)
                verified.extend(matches)
                if index % 10 == 0:
                    print(f"Metadata inspection {index}/{len(targets)} issuers; {len(checked)} filings examined; {len(verified)} verified", flush=True)
        write_csv_atomic(pd.DataFrame(checked), ROOT / "data/processed/metadata_recovery_candidates.csv")
        for row in verified:
            key = str(row["cik"])
            config.setdefault("additional_accessions", {}).setdefault(key, [])
            config["additional_accessions"][key] = sorted(set(config["additional_accessions"][key]+[row["accession"]]))
            config.setdefault("additional_accession_notes", {})[row["accession"]] = "Metadata-mislabeled release: actual primary8-K explicitly contains Item2.02 Results of Operations heading; only inspected because publication quarter was empty. " + row["primary_document_url"]
        if verified:
            write_json_atomic(config, config_path)
            tickers = sorted(set(row["ticker"] for row in verified))
            collect_firms(ROOT, client, scorer, selected[selected.ticker.isin(tickers)], start, end, config["sec_workers"], force=True)
    eog_log = recover_official_ir_text(client, scorer, selected, start, end, "EOG")
    ge_log = recover_official_ir_text(client, scorer, selected, start, end, "GE")
    lhx_log = recover_official_ir_text(client, scorer, selected, start, end, "LHX")
    echostar_log = recover_echostar_exhibits(client, scorer, selected, start, end)
    firms = pd.read_csv(ROOT / "data/processed/firm_scores.csv")
    repair_path = ROOT / "reports/corpus_repairs_full.json"
    if repair_path.exists():
        ledger = json.loads(repair_path.read_text(encoding="utf-8"))
        baseline_path = ROOT / "reports/pilot_baseline.json"
        original_pilot_ids = set(json.loads(baseline_path.read_text(encoding="utf-8")).get("original_document_ids", [])) if baseline_path.exists() else set()
        seen_repairs = {row["doc_id"] for row in ledger["repairs"]}
        old_by_id = primary.set_index("doc_id").to_dict("index")
        for new in firms.to_dict("records"):
            old = old_by_id.get(new["doc_id"])
            if old and new["doc_id"] not in seen_repairs and (new["source_url"] != old["source_url"] or new["text_sha256"] != old["text_sha256"]):
                ledger["repairs"].append(dict(ticker=new["ticker"], doc_id=new["doc_id"], publication_date=old["publication_date"],
                    old_source_url=old["source_url"], old_text_sha256=old["text_sha256"], old_word_count=int(old["word_count"]),
                    reason="Source selection or documented extraction boundary changed during recovery: " + str(new.get("text_scope", "standard release-body extraction")),
                    was_in_original_pilot=new["doc_id"] in original_pilot_ids, review_type="implemented_source_repair_comparison", repair_status="queued"))
        for row in ledger["repairs"]:
            matches = firms[firms.doc_id.eq(row["doc_id"])]
            if len(matches):
                new = matches.iloc[0]
                state = "replaced_exhibit" if new.source_url != row["old_source_url"] else "extraction_scope_repaired" if new.text_sha256 != row["old_text_sha256"] else "reviewed_retained"
                row.update(repair_status=state, new_source_url=new.source_url, new_text_sha256=new.text_sha256, new_word_count=int(new.word_count))
            else:
                row["repair_status"] = "excluded_entire_filing"
        write_json_atomic(ledger, repair_path)
    report = {"finished_at": datetime.now(timezone.utc).isoformat(), "reviewed_issuer_repair_queue": queue,
              "metadata_candidates_inspected": len(checked), "primary_Item2.02_headings_verified": len(verified),
              "echostar_recovered_exhibits": sum(row["status"] == "recovered_SEC_standalone_release_exhibit" for row in echostar_log),
              "eog_official_IR_text_recovered": sum(row["status"] == "official_IR_text_recovered_with_SEC_time" for row in eog_log),
              "ge_official_IR_text_recovered": sum(row["status"] == "official_IR_text_recovered_with_SEC_time" for row in ge_log),
              "lhx_official_IR_original_letters_recovered": sum(row["status"] == "official_IR_text_recovered_with_SEC_time" for row in lhx_log),
              "verified_primary_heading_is_not_sufficient_for_inclusion": "Existing substantive-earnings-exhibit selection still applies.",
              "acceptance_timestamps": "Actual SEC acceptance retained separately. SEC text uses that timestamp; actual IR text uses max(SEC acceptance, midnight America/New_York after the official IR date). Amendments are not backdated.",
              "recovery_count_basis": "Successful source recoveries can replace an existing filing row; these counts are not additive corpus-document totals."}
    write_json_atomic(report, ROOT / "reports/source_recovery_summary.json")
    sessions = json.loads(session_path.read_text(encoding="utf-8")) if session_path.exists() else {"sessions": []}
    sessions["sessions"].append(dict(phase="source_recovery", session_started_at=client.started_at,
        ended_at=datetime.now(timezone.utc).isoformat(), http_requests=client.requests_made,
        status_counts=dict(client.http_status_counts), current_global_sec_requests_per_second=1/client.interval,
        mean_response_seconds_excluding_limiter=client.response_seconds/client.requests_made if client.requests_made else None,
        count_basis="Exact completed network request count for the recovery client; includes official IR requests, excludes disk-cache hits"))
    write_json_atomic(sessions, session_path)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
