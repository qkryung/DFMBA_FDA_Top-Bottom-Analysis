"""Official public-document acquisition with a disk cache and global SEC rate limit.

Raw filings and dictionaries stay local. Metadata/derived scores can be shared.
This does not reconstruct historical S&P500 membership or historical GICS labels.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time
import zipfile
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401
    HTML_PARSER = "lxml"
except ImportError:
    HTML_PARSER = "html.parser"

from .text import TextScorer

UNIVERSE_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
FED_BASE = "https://www.federalreserve.gov"
SEC_BASE = "https://www.sec.gov"


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


@lru_cache(maxsize=1)
def reviewed_exclusions() -> dict:
    path = Path(__file__).resolve().parents[2] / "configs/document_exclusions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def exclusion_reason(text: str, source_url: str) -> str | None:
    """Conservative exclusion of repackaged annual reports misfiled as results exhibits."""
    opening = text[:2500]
    if source_url in reviewed_exclusions():
        return reviewed_exclusions()[source_url]
    if re.search(r"statistical supplement|supplemental information", text[:500], re.I) and not re.search(r"earnings release|reports? .{0,50}(results|earnings)", text[:500], re.I):
        return "Standalone statistical/recast supplement, not an earnings narrative release"
    if re.search(r"condensed consolidated statement of earnings", text[:500], re.I):
        return "Standalone financial-statement table, not an earnings narrative release"
    if re.search(r"analyst meeting|investor day", text[:500], re.I) and not re.search(r"earnings release|reports? .{0,50}(results|earnings)", text[:500], re.I):
        return "Analyst-meeting/investor-day document outside the earnings-release corpus"
    if re.search(r"revised10[kxq]|recast.*10[kq]", source_url, re.I):
        return "Revised annual/quarterly report, not an earnings release"
    if re.search(r"EXPLANATORY NOTE", opening, re.I) and re.search(r"Annual Report on Form 10.K|Quarterly Report on Form 10.Q", opening, re.I):
        return "Explanatory-note annual/quarterly report restatement"
    if re.search(r"unaudited pro forma condensed combined", opening, re.I) and not re.search(r"reports? .*quarter|announces? .*results", opening, re.I):
        return "Transaction pro-forma financial statement, not an earnings release"
    return None


class CachedClient:
    def __init__(self, root: Path, user_agent: str = "", rps: float = 4):
        self.cache = Path(root) / "data/raw/http"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT", "")
        self.lock = threading.Lock()
        self.last_sec = 0.0
        self.interval = 1 / rps

    def get(self, url: str) -> bytes:
        cached = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".bin")
        if cached.exists():
            return cached.read_bytes()
        if "sec.gov" in url and not self.user_agent:
            raise RuntimeError("Set SEC_USER_AGENT to your actual researcher name and contact email. It is not persisted.")
        headers = {"User-Agent": self.user_agent or "DFMBA Top-Bottom academic research https://github.com/qkryung/DFMBA_FDA_Top-Bottom-Analysis"}
        for attempt in range(3):
            if "sec.gov" in url:
                with self.lock:
                    delay = self.interval - (time.monotonic() - self.last_sec)
                    if delay > 0:
                        time.sleep(delay)
                    self.last_sec = time.monotonic()
            response = requests.get(url, headers=headers, timeout=45)
            if response.status_code in (429, 503):
                time.sleep(2 ** (attempt + 1))
                continue
            response.raise_for_status()
            # Do not persist failed HTML masquerading as JSON.
            if url.endswith(".json"):
                response.json()
            cached.write_bytes(response.content)
            return response.content
        raise RuntimeError(f"Rate limited after retries: {url}")


def extract_text(content: bytes, fomc: bool = False) -> str:
    soup = BeautifulSoup(content, HTML_PARSER)
    container = soup.find(id="content") if fomc else soup
    if container is None:
        container = soup
    for tag in container(["script", "style", "noscript", "nav", "footer", "header", "ix:header"]):
        tag.decompose()
    if fomc:
        # Score the comparable assessment sections, excluding participant lists,
        # annual administrative appendices and the repeated formal policy directive.
        text = container.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        start = text.find("Staff Review of the Economic Situation")
        stop = text.find("Committee Policy Action", start)
        if start < 0 or stop <= start:
            raise ValueError("FOMC core assessment section boundaries were not found")
        text = text[start:stop].strip()
    else:
        # Preserve block and cell separators so adjacent words do not concatenate.
        text = container.get_text(" ", strip=True)
        # Older IBM 8-Ks embed the press release as Attachment I rather than EX99.
        embedded = re.search(r"ATTACHMENT\s+I\s+(IBM\s+REPORTS)", text)
        if embedded:
            start = embedded.start(1)
            following = re.search(r"ATTACHMENT\s+II\b", text[start:])
            if following:
                text = text[start:start+following.start()]
    return re.sub(r"[ \t\xa0]+", " ", text).strip()


def prepare_dictionaries(root: Path, zip_path: Path) -> dict:
    out = root / "data/raw/dictionaries"
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"method": "Loughran-McDonald", "version": "course archive 20200204", "redistributed": False,
                "official_reference": "https://sraf.nd.edu/loughranmcdonald-master-dictionary/", "files": []}
    with zipfile.ZipFile(zip_path) as archive:
        for label in ("Positive", "Negative", "Uncertainty"):
            filename = f"LoughranMcDonald_{label}.csv"
            match = next(n for n in archive.namelist() if n.endswith("/"+filename) or n == filename)
            data = archive.read(match)
            (out / filename).write_bytes(data)
            manifest["files"].append({"filename": filename, "sha256": hashlib.sha256(data).hexdigest(),
                                      "word_count": len(data.decode("utf-8-sig").splitlines())})
    (root / "data/reference/dictionary_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    return manifest


def load_universe(root: Path, client: CachedClient) -> pd.DataFrame:
    raw = client.get(UNIVERSE_URL)
    frame = pd.read_csv(io.BytesIO(raw)).rename(columns={"Symbol": "ticker", "Security": "company", "GICS Sector": "sector", "CIK": "cik"})
    frame = frame[["ticker", "company", "sector", "cik"]].copy()
    frame["cik"] = frame["cik"].astype(int)
    cache_file = client.cache / (hashlib.sha256(UNIVERSE_URL.encode()).hexdigest() + ".bin")
    frame["snapshot_retrieved_at"] = datetime.fromtimestamp(cache_file.stat().st_mtime, timezone.utc).isoformat()
    frame["source_url"] = UNIVERSE_URL
    write_csv_atomic(frame,root / "data/reference/universe_snapshot.csv")
    return frame


def save_document(root: Path, record: dict, text: str, scorer: TextScorer) -> dict:
    path = root / "data/raw/text" / (record["doc_id"] + ".txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    record.update(scorer.score(text))
    cached = root / "data/raw/http" / (hashlib.sha256(record["source_url"].encode()).hexdigest() + ".bin")
    record["retrieved_at"] = datetime.fromtimestamp(cached.stat().st_mtime,timezone.utc).isoformat() if cached.exists() else datetime.now(timezone.utc).isoformat()
    record["scored_at"] = datetime.now(timezone.utc).isoformat()
    return record


def collect_fomc(root: Path, client: CachedClient, scorer: TextScorer, start: int, end: int) -> list[dict]:
    records = []
    for year in range(start, end + 1):
        url = f"{FED_BASE}/monetarypolicy/fomchistorical{year}.htm"
        try:
            calendar_html = client.get(url)
        except requests.HTTPError as error:
            if error.response.status_code != 404:
                raise
            url = f"{FED_BASE}/monetarypolicy/fomccalendars.htm"
            calendar_html = client.get(url)
        soup = BeautifulSoup(calendar_html, HTML_PARSER)
        found = {}
        for a in soup.find_all("a", href=True):
            match = re.search(r"fomcminutes(\d{8})\.htm", a["href"])
            if not match:
                continue
            if int(match.group(1)[:4]) != year:
                continue
            meeting = datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
            release = re.search(r"Released\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", a.parent.get_text(" ", strip=True))
            if not release:
                continue
            date = datetime.strptime(release.group(1), "%B %d, %Y")
            published = date.replace(hour=14, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
            found[meeting] = (urljoin(FED_BASE, a["href"]), published)
        if not found:
            raise ValueError(f"No FOMC minutes release dates found for {year}")
        for meeting, (source, published) in sorted(found.items()):
            text = extract_text(client.get(source), fomc=True)
            row = dict(doc_id="fomc_" + meeting, meeting_date=meeting, published_at=published.isoformat(),
                       publication_date=published.date().isoformat(), document_type="FOMC_minutes", source_url=source,
                       calendar_source_url=url, publication_time_basis="Official release date; standard minutes release time 14:00 Eastern")
            row["text_scope"] = "Staff review, staff outlook and participants' views; before Committee Policy Action"
            records.append(save_document(root, row, text, scorer))
        write_csv_atomic(pd.DataFrame(records), root / "data/processed/fomc_scores.csv")
        print(f"FOMC {year}: {len(found)} minutes; total {len(records)}", flush=True)
    return records


def filing_rows(client: CachedClient, cik: int, start: int, end: int) -> list[dict]:
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    data = json.loads(client.get(url))
    blocks = [data["filings"]["recent"]]
    for past in data["filings"].get("files", []):
        if past.get("filingTo", "") >= f"{start}-01-01" and past.get("filingFrom", "") <= f"{end}-12-31":
            blocks.append(json.loads(client.get("https://data.sec.gov/submissions/" + past["name"])))
    result = {}
    configuration = json.loads((Path(__file__).resolve().parents[2]/"configs/research.json").read_text(encoding="utf-8"))
    explicitly_included = configuration.get("additional_accessions", {}).get(str(cik), [])
    for block in blocks:
        for i, form in enumerate(block.get("form", [])):
            date = block["filingDate"][i]
            items = block.get("items", [""] * len(block["form"]))[i]
            if form != "8-K" or ("2.02" not in items and block["accessionNumber"][i] not in explicitly_included) or not (f"{start}-01-01" <= date <= f"{end}-12-31"):
                continue
            row = {k: values[i] for k, values in block.items() if isinstance(values, list) and len(values) > i}
            result[row["accessionNumber"]] = row
    return sorted(result.values(), key=lambda x: x["filingDate"])


def earnings_exhibit(client: CachedClient, cik: int, filing: dict) -> tuple[str, bytes]:
    accession = filing["accessionNumber"]
    directory = f"{SEC_BASE}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    index_url = directory + accession + "-index.html"
    soup = BeautifulSoup(client.get(index_url), HTML_PARSER)
    candidates = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        dtype = cells[3].get_text(" ", strip=True).upper()
        if not dtype.startswith("EX-99"):
            continue
        link = cells[2].find("a", href=True)
        if not link:
            continue
        source = urljoin(SEC_BASE, link["href"])
        # XBRL viewer URLs, if used, wrap the actual filing URL.
        source = source.replace("/ix?doc=", "").replace("/ixviewer/doc/action?doc=", "")
        description = cells[1].get_text(" ", strip=True).lower()
        rank = 40 * bool(re.search(r"press release|financial results", description)) + 10 * bool(re.search(r"earnings", description)) + 20 * (dtype.startswith("EX-99.1") or dtype == "EX-99")
        if source.lower().endswith((".htm", ".html", ".txt")):
            candidates.append((rank, source))
    for _, source in sorted(candidates, reverse=True):
        content = client.get(source)
        text = extract_text(content)
        if exclusion_reason(text, source):
            continue
        # Item2.02 includes preliminary results and updates; keep only a substantive
        # financial-results exhibit and label the corpus accordingly.
        if len(text) >= 1000 and re.search(r"quarter|annual|year.end|full.year", text, re.I) and re.search(r"earnings|revenue|net income|financial results|results of operations", text, re.I):
            return source, content
    # Strictly bounded recovery for identifiable embedded releases; do not score
    # a whole generic 8-K with signatures, slides and other attachments.
    primary = directory + filing["primaryDocument"]
    content = client.get(primary)
    text = extract_text(content)
    if text.startswith("IBM REPORTS") and len(text) >= 1000:
        return primary, content
    raise ValueError("No substantive HTML earnings-results EX-99 exhibit found")


def collect_company(root: Path, client: CachedClient, scorer: TextScorer, company: dict, start: int, end: int, include_history: bool = True) -> tuple[list, list]:
    records, failures = [], []
    ticker, cik = company["ticker"], int(company["cik"])
    try:
        filings = filing_rows(client, cik, start, end)
    except Exception as error:
        return [], [{"ticker": ticker, "stage": "submissions", "error": str(error)}]
    for filing in filings:
        accession = filing["accessionNumber"]
        try:
            source, content = earnings_exhibit(client, cik, filing)
            published = filing.get("acceptanceDateTime")
            basis = "SEC acceptance datetime UTC; may lag original issuer release"
            if not published:
                # Date-only filings are conservatively available at next calendar day.
                published = (pd.Timestamp(filing["filingDate"]) + pd.Timedelta(days=1)).isoformat() + "Z"
                basis = "No SEC timestamp; conservative next-calendar-day 00:00 UTC"
            record = dict(doc_id=f"sec_{cik}_{accession}", ticker=ticker, company=company["company"],
                          sector=company["sector"], cik=cik, published_at=published,
                          publication_date=filing["filingDate"], document_type="SEC_8K_Item2.02_EX99_earnings_release",
                          source_url=source, accession=accession, publication_time_basis=basis)
            record["sec_item_tags"] = filing.get("items", "")
            if "2.02" not in filing.get("items", ""):
                record["document_type"] = "SEC_8K_EX99_earnings_release_reviewed_Item2.01_tag"
            if source.endswith("/" + filing["primaryDocument"]):
                record["document_type"] = "SEC_8K_embedded_earnings_release"
                record["text_scope"] = "Identified embedded press release Attachment I; excludes Attachment II slides"
            records.append(save_document(root, record, extract_text(content), scorer))
        except Exception as error:
            failures.append({"ticker": ticker, "accession": accession, "filing_date": filing["filingDate"], "stage": "exhibit", "error": str(error)})
    if include_history:
        configuration = json.loads((root/"configs/research.json").read_text(encoding="utf-8"))
        for historical in configuration.get("additional_historical_ciks", {}).get(ticker, []):
            history_start, history_end = max(start,historical["start_year"]), min(end,historical["end_year"])
            if history_start > history_end:
                continue
            historic_company = dict(company, cik=historical["cik"])
            old_rows, old_failures = collect_company(root,client,scorer,historic_company,history_start,history_end,include_history=False)
            records.extend(row for row in old_rows if row["publication_date"] <= historical["valid_through_date"])
            failures.extend(row for row in old_failures if row.get("filing_date","") <= historical["valid_through_date"])
    print(f"SEC {ticker} CIK {cik}: {len(records)} releases; {len(filings)} primary-CIK candidate filings", flush=True)
    return records, failures


def collect_firms(root: Path, client: CachedClient, scorer: TextScorer, universe: pd.DataFrame, start: int, end: int, workers: int = 4) -> tuple[list, list]:
    records, failures = [], []
    existing = root / "data/processed/firm_scores.csv"
    if existing.exists():
        prior = pd.read_csv(existing)
        records = prior[~prior.ticker.isin(universe.ticker)].to_dict("records")
    failure_path = root / "data/processed/acquisition_failures.csv"
    if failure_path.exists():
        prior_failures = pd.read_csv(failure_path)
        failures = prior_failures[~prior_failures.ticker.isin(universe.ticker)].to_dict("records")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(collect_company, root, client, scorer, row, start, end) for row in universe.to_dict("records")]
        for future in as_completed(futures):
            rows, errors = future.result()
            records.extend(rows)
            failures.extend(errors)
            if records:
                write_csv_atomic(pd.DataFrame(records).sort_values(["ticker", "published_at"]), root / "data/processed/firm_scores.csv")
            write_csv_atomic(pd.DataFrame(failures, columns=["ticker", "accession", "filing_date", "stage", "error"]), root / "data/processed/acquisition_failures.csv")
    return records, failures


def write_manifest(root: Path) -> None:
    frames = []
    for name in ("firm_scores", "fomc_scores"):
        path = root / "data/processed" / (name + ".csv")
        if path.exists():
            frame = pd.read_csv(path)
            cols = [c for c in ("doc_id", "ticker", "company", "sector", "document_type", "published_at", "publication_date", "meeting_date", "source_url", "calendar_source_url", "publication_time_basis", "text_sha256", "retrieved_at") if c in frame]
            frames.append(frame[cols])
    if frames:
        write_csv_atomic(pd.concat(frames, ignore_index=True),root / "data/processed/source_manifest.csv")


def write_coverage(root: Path, selected: pd.DataFrame, config: dict) -> dict:
    firm_path, fed_path = root/"data/processed/firm_scores.csv", root/"data/processed/fomc_scores.csv"
    firms = pd.read_csv(firm_path) if firm_path.exists() else pd.DataFrame()
    fed = pd.read_csv(fed_path) if fed_path.exists() else pd.DataFrame()
    failures = pd.read_csv(root/"data/processed/acquisition_failures.csv") if (root/"data/processed/acquisition_failures.csv").exists() else pd.DataFrame()
    report = {"status": "executed_pilot", "start_year": config["start_year"], "end_year": config["end_year"],
              "target_companies": len(selected), "covered_companies": int(firms.ticker.nunique()) if len(firms) else 0,
              "missing_companies": sorted(set(selected.ticker) - set(firms.ticker if len(firms) else [])),
              "firm_documents": len(firms), "fomc_documents": len(fed), "failed_acquisitions": len(failures),
              "universe_basis": config["universe_basis"], "sectors": {},
              "limitations": ["Current constituent snapshot and current GICS labels create survivorship and classification bias.",
                "Pilot companies selected deliberately; not a random or complete S&P500 sample.",
                "SEC Item 2.02 exhibits are issuer earnings releases, not earnings-call transcripts.",
                "Some Item2.02 filings are preliminary updates; more than four filings per year is possible.",
                "Acceptance timestamp is conservative relative to the original issuer press-release time.",
                "LM tone measures positive/negative language, not macroeconomic direction or causal impact.",
                "Keyword topics overlap and require human-label validation before investment use.",
                "Forward-looking text identification and boilerplate removal are rule-based heuristics."]}
    if len(firms):
        report["firm_date_min"] = firms.publication_date.min()
        report["firm_date_max"] = firms.publication_date.max()
        report["duplicate_doc_ids"] = int(firms.doc_id.duplicated().sum())
        report["sectors"] = firms.groupby("sector").agg(companies=("ticker", "nunique"), documents=("doc_id", "size")).to_dict("index")
        write_csv_atomic(firms.assign(year=pd.to_datetime(firms.publication_date).dt.year).groupby(["ticker", "sector", "year"]).size().rename("documents").reset_index(),root/"data/processed/coverage_by_company_year.csv")
    if len(fed):
        report["fomc_date_min"] = fed.publication_date.min()
        report["fomc_date_max"] = fed.publication_date.max()
        report["fomc_by_meeting_year"] = fed.assign(year=pd.to_datetime(fed.meeting_date).dt.year).groupby("year").size().to_dict()
    (root/"reports/data_coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    write_manifest(root)
    return report
