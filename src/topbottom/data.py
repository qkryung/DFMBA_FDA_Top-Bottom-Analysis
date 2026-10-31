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
from collections import Counter, deque
from functools import lru_cache
from itertools import islice
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401
    from lxml import html as lxml_html
    HTML_PARSER = "lxml"
except ImportError:
    HTML_PARSER = "html.parser"

from .text import TextScorer, TOKEN, SENTENCE, SAFE_HARBOR

UNIVERSE_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
FED_BASE = "https://www.federalreserve.gov"
SEC_BASE = "https://www.sec.gov"


def replace_atomic(temporary: Path, destination: Path) -> None:
    """Tolerate brief Windows reader/OneDrive locks without exposing partial CSVs."""
    for attempt in range(9):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if attempt == 8:
                raise
            time.sleep(min(0.05 * 2 ** attempt, 1.0))


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    replace_atomic(temporary, path)


def write_json_atomic(value: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")
    replace_atomic(temporary, path)


def conservative_ir_available_at(sec_acceptance: str, release_date: str) -> str:
    """Date-only US issuer IR release is usable after its New York calendar day."""
    next_day = (pd.Timestamp(release_date) + pd.Timedelta(days=1)).tz_localize(ZoneInfo("America/New_York")).tz_convert("UTC")
    return max(pd.Timestamp(sec_acceptance), next_day).isoformat()


def classify_failure(error: Exception | str) -> str:
    message = str(error).lower()
    if "reviewed filing excluded" in message:
        return "reviewed_source_scope_exclusion"
    if "image-embedded earnings narrative" in message:
        return "earnings_narrative_image_only_no_text_layer"
    if "no substantive" in message:
        return "no_qualifying_earnings_exhibit"
    if "404" in message:
        return "http_404"
    if any(s in message for s in ("403", "429", "rate limited")):
        return "http_access_or_rate_limit"
    if any(s in message for s in ("timeout", "timed out", "connection", "503", "502")):
        return "network_transient"
    return "parse_or_other_error"


@lru_cache(maxsize=1)
def reviewed_exclusions() -> dict:
    path = Path(__file__).resolve().parents[2] / "configs/document_exclusions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@lru_cache(maxsize=1)
def source_recovery() -> dict:
    path = Path(__file__).resolve().parents[2] / "configs/source_recovery.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def exclusion_reason(text: str, source_url: str) -> str | None:
    """Conservative exclusion of repackaged annual reports misfiled as results exhibits."""
    # Classification ignores layout-only whitespace; the score input is untouched.
    text = " ".join(text.split())
    opening = text[:2500]
    if source_url in source_recovery().get("document_allowlist", {}):
        return None
    if source_url in reviewed_exclusions():
        return reviewed_exclusions()[source_url]
    if re.search(r"Order Routing Public Report|Rule\s*606\s+(?:Public\s+)?Report", text[:1000], re.I):
        return "Rule606 order-routing disclosure, not a corporate earnings release or financial-guidance narrative"
    if re.search(r"earnings\s+(?:conference\s+)?call|financial results\s+presentation", text[:350], re.I) and not re.search(r"\b(?:reports|announces)\b|provides\s+(?:an?\s+)?update|press release|earnings release", text[:350], re.I):
        return "Earnings-call presentation/transcript heading without a press-release narrative heading"
    if sum(1 for _ in islice(re.finditer(r"\b[A-Za-z]+\b", text), 600)) < 600 and re.search(r"posted.{0,80}(?:letter|financial results).{0,180}(?:Investor Relations|website)", text, re.I) and not re.search(r"[$\u20ac\u00a3]\s*\d|(?:revenue|net income|earnings per share).{0,30}\d", text, re.I):
        return "Results-availability notice; substantive shareholder letter/results are a separate exhibit"
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


def points_to_shareholder_letter(text: str) -> bool:
    compact = " ".join(text.split())
    return sum(1 for _ in islice(TOKEN.finditer(text), 700)) < 700 and bool(re.search(
        r"(?:posted|available|published).{0,160}(?:letter to (?:our |its )?shareholders|shareholder letter|investor letter)|(?:letter to shareholders|shareholder letter|investor letter).{0,160}(?:posted|available|website)",
        compact, re.I))


def has_substantive_narrative(text: str) -> bool:
    """Require analyzable narrative after the same sentence/boilerplate rules."""
    sentences, words = 0, 0
    for sentence in SENTENCE.split(text):
        count = len(TOKEN.findall(sentence))
        if count >= 5 and not SAFE_HARBOR.search(sentence):
            sentences += 1
            words += count
            if sentences > 2 and words >= 100:
                return True
    return False


class CachedClient:
    def __init__(self, root: Path, user_agent: str = "", rps: float = 4):
        self.cache = Path(root) / "data/raw/http"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT", "")
        self.lock = threading.Lock()
        self.last_sec = 0.0
        self.interval = 1 / rps
        self.local = threading.local()
        self.requests_made = 0
        self.response_seconds = 0.0
        self.http_status_counts = Counter()
        self.request_times = deque(maxlen=1000)
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.metrics_path = Path(root) / "reports/acquisition_http_metrics.json"

    def get(self, url: str) -> bytes:
        cached = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".bin")
        if cached.exists():
            return cached.read_bytes()
        is_sec = (urlparse(url).hostname or "").lower() in ("sec.gov", "www.sec.gov", "data.sec.gov", "archives.sec.gov")
        if is_sec and not self.user_agent:
            raise RuntimeError("Set SEC_USER_AGENT to your actual researcher name and contact email. It is not persisted.")
        headers = {"User-Agent": self.user_agent if is_sec else "DFMBA Top-Bottom academic research https://github.com/qkryung/DFMBA_FDA_Top-Bottom-Analysis"}
        for attempt in range(3):
            if is_sec:
                with self.lock:
                    delay = self.interval - (time.monotonic() - self.last_sec)
                    if delay > 0:
                        time.sleep(delay)
                    self.last_sec = time.monotonic()
            if not hasattr(self.local, "session"):
                self.local.session = requests.Session()
            request_started = time.monotonic()
            try:
                response = self.local.session.get(url, headers=headers, timeout=45)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))
                continue
            with self.lock:
                self.requests_made += 1
                self.response_seconds += time.monotonic()-request_started
                self.http_status_counts[str(response.status_code)] += 1
                self.request_times.append(time.monotonic())
                if response.status_code in (403, 429, 503):
                    self.interval = max(self.interval, .25)
                if self.requests_made % 100 == 0 or response.status_code in (403, 429, 503):
                    write_json_atomic({"session_started_at": self.started_at, "updated_at": datetime.now(timezone.utc).isoformat(),
                                       "http_requests": self.requests_made, "status_counts": dict(self.http_status_counts),
                                       "mean_response_seconds_excluding_limiter": self.response_seconds/self.requests_made,
                                       "requests_last_60_seconds": sum(t > time.monotonic()-60 for t in self.request_times),
                                       "current_global_sec_requests_per_second": 1/self.interval}, self.metrics_path)
            if response.status_code in (403, 429, 503):
                time.sleep(min(60, max(2 ** (attempt + 1), int(response.headers.get("Retry-After", "0")) if response.headers.get("Retry-After", "0").isdigit() else 0)))
                continue
            response.raise_for_status()
            # Do not persist failed HTML masquerading as JSON.
            if url.endswith(".json"):
                response.json()
            temporary = cached.with_suffix(f".{threading.get_ident()}.tmp")
            temporary.write_bytes(response.content)
            os.replace(temporary, cached)
            return response.content
        raise RuntimeError(f"Rate limited after retries: {url}")


def extract_earnings_section(text: str) -> str:
    """Bounded recovery of reviewed combined or embedded earnings releases."""
    start = re.search(r"Alexandria Real Estate Equities,\s*Inc\.\s+Reports\b", text, re.I)
    if start:
        end = re.search(r"SUPPLEMENTAL INFORMATION\s+Company Profile\b", text[start.start():], re.I)
        if end:
            return text[start.start():start.start()+end.start()].strip()
    start = re.search(r"Federal Realty Investment Trust\s+(?:Announces|Reports)\b", text, re.I)
    if start:
        end = re.search(r"Federal Realty Investment Trust\s+(?:Summarized|Consolidated)\s+Income Statements", text[start.start():], re.I)
        if end:
            return text[start.start():start.start()+end.start()].strip()
    start = re.search(r"The text of the Press Release is as follows:\s*(?:FOR IMMEDIATE RELEASE\s+)?(HALLIBURTON\s+(?:ANNOUNCES|PROVIDES)\b)", text, re.I)
    if start:
        end = re.search(r"SIGNATURES\s+Pursuant to the requirements", text[start.end():], re.I)
        if end:
            return text[start.start(1):start.end()+end.start()].strip()
    # Reviewed NXP filings put the full release after the completed SEC signature
    # block. Requiring both markers avoids mistaking the cover's quoted title for
    # the release itself; later financial statements are part of that release.
    signature = re.search(r"SIGNATURES\s+Pursuant to the requirements", text, re.I)
    if signature:
        start = re.search(r"NXP\s+Semiconductors\s+Reports\s+(?:First|Second|Third|Fourth)\s+Quarter\b", text[signature.end():], re.I)
        if start:
            return text[signature.end()+start.start():].strip()
    # CRH used primary 6-K results announcements with an appended full interim
    # financial report. Select the announced results/management narrative only.
    if re.search(r"CRH\s+public\s+limited\s+company", text[:1500], re.I):
        cover = re.search(r"Regulation\s+S-T\s+Rule\s+101\(b\)\(7\)", text, re.I)
        if cover:
            start = re.search(r"\b20\d{2}\s+(?:Interim|Half[ -]Year|Full[ -]Year)\s+Results\b", text[cover.end():], re.I)
            if start:
                offset = cover.end()+start.start()
                end = re.search(r"(?:Condensed\s+)?Consolidated\s+Income\s+Statement\b", text[offset:], re.I)
                if end:
                    return text[offset:offset+end.start()].strip()
    return text


def extract_text_reference(content: bytes, fomc: bool = False) -> str:
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
    text = re.sub(r"[ \t\xa0]+", " ", text).strip()
    return text if fomc else extract_earnings_section(text)


@lru_cache(maxsize=64)
def extract_text(content: bytes, fomc: bool = False) -> str:
    """Content-keyed bounded cache; equal bytes are required for a cache hit.

    The direct lxml path is regression-checked against the original BeautifulSoup
    parser. FOMC section selection retains its original parser and boundaries.
    """
    if content.lstrip().startswith(b"%PDF"):
        if hashlib.sha256(content).hexdigest() in source_recovery().get("pdf_pymupdf_overrides", {}):
            import pymupdf
            with pymupdf.open(stream=content, filetype="pdf") as document:
                text = "\n".join(page.get_text() for page in document)
        else:
            from pypdf import PdfReader
            pages = PdfReader(io.BytesIO(content)).pages
            text = "\n".join(page.extract_text() or "" for page in pages)
        return extract_earnings_section(re.sub(r"[ \t\xa0]+", " ", text).strip())
    fallback = source_recovery().get("parser_fallback_sha256", [])
    if fomc or HTML_PARSER != "lxml" or hashlib.sha256(content).hexdigest() in fallback:
        return extract_text_reference(content, fomc=fomc)
    try:
        tree = lxml_html.fromstring(content)
        for tag in tree.xpath('//script|//style|//noscript|//nav|//footer|//header|//*[name()="ix:header"]'):
            tag.drop_tree()
        text = " ".join(value.strip() for value in tree.xpath('//text()') if value.strip())
        # Legacy numeric CP1252 entities are handled inconsistently across HTML
        # parser families. Preserve the established reference parser for every
        # such input, rather than maintaining a document-specific exception list.
        if re.search(r"[\x80-\x9f]", text):
            return extract_text_reference(content, fomc=False)
        embedded = re.search(r"ATTACHMENT\s+I\s+(IBM\s+REPORTS)", text)
        if embedded:
            start = embedded.start(1)
            following = re.search(r"ATTACHMENT\s+II\b", text[start:])
            if following:
                text = text[start:start+following.start()]
        return extract_earnings_section(re.sub(r"[ \t\xa0]+", " ", text).strip())
    except (ValueError, TypeError, lxml.etree.ParserError):
        return extract_text_reference(content, fomc=False)


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


def load_universe(root: Path, client: CachedClient, refresh: bool = False) -> pd.DataFrame:
    # A rerun must not silently change the study's constituent universe.
    snapshot = root / "data/reference/universe_snapshot.csv"
    if snapshot.exists() and not refresh:
        return pd.read_csv(snapshot)
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
    # The score hash describes the canonical UTF-8/LF input used by every later
    # read, audit and model. HTML-internal CRLF must not create platform drift.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    path = root / "data/raw/text" / (record["doc_id"] + ".txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    record.update(scorer.score(text))
    cached = root / "data/raw/http" / (hashlib.sha256(record["source_url"].encode()).hexdigest() + ".bin")
    record["retrieved_at"] = datetime.fromtimestamp(cached.stat().st_mtime,timezone.utc).isoformat() if cached.exists() else datetime.now(timezone.utc).isoformat()
    record["scored_at"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(record, root / "data/raw/document_records" / (record["doc_id"] + ".json"))
    return record


def collect_fomc(root: Path, client: CachedClient, scorer: TextScorer, start: int, end: int) -> list[dict]:
    records = []
    existing_path = root / "data/processed/fomc_scores.csv"
    existing = {row["doc_id"]: row for row in pd.read_csv(existing_path).to_dict("records")} if existing_path.exists() else {}
    # December minutes are normally released in January of the following year.
    # This is a publication-year sample, so inspect the preceding meeting year.
    for year in range(start - 1, end + 1):
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
            if not start <= published.year <= end:
                continue
            doc_id = "fomc_" + meeting
            if doc_id in existing:
                records.append(existing[doc_id])
                continue
            text = extract_text(client.get(source), fomc=True)
            row = dict(doc_id=doc_id, meeting_date=meeting, published_at=published.isoformat(),
                       publication_date=published.date().isoformat(), document_type="FOMC_minutes", source_url=source,
                       calendar_source_url=url, publication_time_basis="Official release date; standard minutes release time 14:00 Eastern")
            row["text_scope"] = "Staff review, staff outlook and participants' views; before Committee Policy Action"
            records.append(save_document(root, row, text, scorer))
        write_csv_atomic(pd.DataFrame(records), root / "data/processed/fomc_scores.csv")
        print(f"FOMC {year}: {len(found)} minutes; total {len(records)}", flush=True)
    return records


def filing_rows(client: CachedClient, cik: int, start: int, end: int, include_unlabeled: bool = False, include_forms: tuple = ()) -> list[dict]:
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    data = json.loads(client.get(url))
    blocks = [data["filings"]["recent"]]
    for past in data["filings"].get("files", []):
        if past.get("filingTo", "") >= f"{start}-01-01" and past.get("filingFrom", "") <= f"{end}-12-31":
            blocks.append(json.loads(client.get("https://data.sec.gov/submissions/" + past["name"])))
    result = {}
    period_forms = {}
    period_dates = []
    configuration = json.loads((Path(__file__).resolve().parents[2]/"configs/research.json").read_text(encoding="utf-8"))
    explicitly_included = configuration.get("additional_accessions", {}).get(str(cik), [])
    for block in blocks:
        for i, form in enumerate(block.get("form", [])):
            date = block["filingDate"][i]
            items = block.get("items", [""] * len(block["form"]))[i]
            if not (f"{start}-01-01" <= date <= f"{end}-12-31"):
                continue
            period_forms[form] = period_forms.get(form, 0) + 1
            period_dates.append(date)
            eligible_8k = (form == "8-K" and "2.02" in items) or (form in ("8-K", "8-K/A") and block["accessionNumber"][i] in explicitly_included)
            # Foreign private issuers and firms that changed registration regime
            # can publish the same earnings press release as a 6-K EX99 exhibit.
            if not eligible_8k and form != "6-K" and form not in include_forms and not (include_unlabeled and form == "8-K"):
                continue
            row = {k: values[i] for k, values in block.items() if isinstance(values, list) and len(values) > i}
            result[row["accessionNumber"]] = row
    profile = {"cik": cik, "name": data.get("name"), "tickers": data.get("tickers"),
               "former_names": data.get("formerNames"), "entity_type": data.get("entityType"),
               "sic": data.get("sic"), "source_url": url, "study_period_forms": period_forms,
               "study_period_first_filing": min(period_dates) if period_dates else None,
               "study_period_last_filing": max(period_dates) if period_dates else None,
               "candidate_filings": len(result), "start_year": start, "end_year": end}
    if hasattr(client, "cache"):
        write_json_atomic(profile, client.cache.parent / "issuer_profiles" / f"{cik}.json")
    return sorted(result.values(), key=lambda x: x["filingDate"])


def earnings_exhibit(client: CachedClient, cik: int, filing: dict) -> tuple[str, bytes]:
    accession = filing["accessionNumber"]
    closure = source_recovery().get("closed_unverified_filings", {}).get(accession)
    if closure:
        raise ValueError("Reviewed filing excluded: " + closure["reason"])
    override = source_recovery().get("exhibit_overrides", {}).get(accession)
    if override:
        content = client.get(override["source_url"])
        text = extract_text(content)
        if len(text) < 1000 or not has_substantive_narrative(text) or not re.search(r"earnings|financial results|revenue", text, re.I):
            raise ValueError("Reviewed exhibit override no longer contains substantive financial results")
        return override["source_url"], content
    directory = f"{SEC_BASE}/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    index_url = directory + accession + "-index.html"
    soup = BeautifulSoup(client.get(index_url), HTML_PARSER)
    candidates = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        dtype = cells[3].get_text(" ", strip=True).upper()
        nxp_numbered_exhibit = cik == 1413447 and filing.get("form") == "6-K" and dtype == "EX-1"
        if not dtype.startswith("EX-99") and not nxp_numbered_exhibit:
            continue
        link = cells[2].find("a", href=True)
        if not link:
            continue
        source = urljoin(SEC_BASE, link["href"])
        # XBRL viewer URLs, if used, wrap the actual filing URL.
        source = source.replace("/ix?doc=", "").replace("/ixviewer/doc/action?doc=", "")
        description = cells[1].get_text(" ", strip=True).lower()
        first_exhibit = dtype.startswith("EX-99.1") or bool(re.match(r"EX-99\.0+1(?:\D|$)", dtype)) or dtype == "EX-99"
        rank = 40 * bool(re.search(r"press release|financial results", description)) + 10 * bool(re.search(r"earnings", description)) + 20 * first_exhibit + 30 * bool(re.search(r"pressrelease|earningsrelease", source, re.I))
        if source.lower().endswith((".htm", ".html", ".txt", ".pdf")):
            candidates.append((rank, source))
    deferred_notice = None
    image_only_narrative = False
    for _, source in sorted(candidates, reverse=True):
        content = client.get(source)
        text = extract_text(content)
        if cik == 1413447 and not re.search(r"NXP\s+Semiconductors\s+Reports\s+(?:First|Second|Third|Fourth)\s+Quarter", text[:2000], re.I):
            continue
        excluded_reason = exclusion_reason(text, source)
        if excluded_reason:
            image_only_narrative = image_only_narrative or "narrative is image-embedded" in excluded_reason.lower()
            continue
        required_heading = filing.get("required_issuer_heading")
        if required_heading and not re.search(required_heading, " ".join(text[:3500].split()), re.I):
            continue
        # Item2.02 includes preliminary results and updates; keep only a substantive
        # financial-results exhibit and label the corpus accordingly.
        financial_content = len(text) >= 1000 and has_substantive_narrative(text) and re.search(r"quarter|annual|year.end|full.year|half.year|interim results", text, re.I) and re.search(r"earnings|revenue|net income|financial results|results of operations", text, re.I)
        foreign_release = filing.get("form") != "6-K" or re.search(r"(?:reports?|announces?|releases?|financial|quarterly|annual|year.end|full.year).{0,100}(?:results|earnings)|earnings release|results (?:for|of) (?:the|its)", " ".join(text[:2000].split()), re.I)
        if financial_content and foreign_release:
            if points_to_shareholder_letter(text):
                # Some notices contain real headline results. Prefer the fuller
                # letter, but retain those facts if no substantive alternative exists.
                deferred_notice = deferred_notice or (source, content)
                continue
            return source, content
    if deferred_notice:
        return deferred_notice
    # Strictly bounded recovery for identifiable embedded releases; do not score
    # a whole generic 8-K with signatures, slides and other attachments.
    primary = directory + filing["primaryDocument"]
    content = client.get(primary)
    text = extract_text(content)
    if cik == 849395 and filing.get("form") == "6-K" and re.match(r"20\d{2}\s+(?:Interim|Half[ -]Year|Full[ -]Year)\s+Results\b", text, re.I) and re.search(r"Chief\s+Executive|\bCEO\b", text, re.I) and re.search(r"revenue|sales|EBITDA", text, re.I) and has_substantive_narrative(text):
        return primary, content
    if (text.startswith("IBM REPORTS") or (cik == 45012 and re.match(r"HALLIBURTON (?:ANNOUNCES|PROVIDES)", text, re.I)) or (cik == 1413447 and re.match(r"NXP\s+Semiconductors\s+Reports\s+(?:First|Second|Third|Fourth)\s+Quarter", text, re.I))) and len(text) >= 1000 and has_substantive_narrative(text):
        return primary, content
    if image_only_narrative:
        raise ValueError("Image-embedded earnings narrative has no usable text layer; supplemental tables are not a substitute")
    raise ValueError("No substantive HTML/PDF earnings-results EX-99 exhibit found")


def collect_company(root: Path, client: CachedClient, scorer: TextScorer, company: dict, start: int, end: int, include_history: bool = True) -> tuple[list, list]:
    records, failures = [], []
    ticker, cik = company["ticker"], int(company["cik"])
    periodic_rule = source_recovery().get("periodic_release_exhibits", {}).get(ticker, {})
    try:
        filings = filing_rows(client, cik, start, end, include_forms=tuple(periodic_rule.get("forms", [])))
        filings = [filing for filing in filings if filing.get("form") not in periodic_rule.get("forms", []) or filing["filingDate"] <= periodic_rule["valid_through_date"]]
    except Exception as error:
        return [], [{"ticker": ticker, "cik": cik, "stage": "submissions", "error_category": classify_failure(error), "error": str(error)}]
    for filing in filings:
        if filing.get("form") in periodic_rule.get("forms", []):
            filing = dict(filing, required_issuer_heading=periodic_rule["required_issuer_heading"])
        accession = filing["accessionNumber"]
        try:
            closure = source_recovery().get("closed_unverified_filings", {}).get(accession)
            if closure:
                raise ValueError("Reviewed filing excluded: " + closure["reason"])
            checkpoint = root / "data/raw/document_records" / f"sec_{cik}_{accession}.json"
            if checkpoint.exists():
                saved = json.loads(checkpoint.read_text(encoding="utf-8"))
                cached_text = root / "data/raw/text" / (saved["doc_id"] + ".txt")
                old_text = cached_text.read_text(encoding="utf-8") if cached_text.exists() else ""
                override = source_recovery().get("exhibit_overrides", {}).get(accession)
                compatible_source = not override or saved.get("source_url") == override["source_url"]
                if ticker not in source_recovery().get("reparse_tickers", []) and saved.get("doc_id") not in source_recovery().get("reparse_doc_ids", []) and saved.get("ticker") == ticker and old_text and compatible_source and saved.get("word_count",0) >= 100 and saved.get("sentence_count",0) > 2 and not exclusion_reason(old_text, saved["source_url"]) and not points_to_shareholder_letter(old_text) and hashlib.sha256(old_text.encode()).hexdigest() == saved.get("text_sha256"):
                    records.append(saved)
                    continue
            source, content = earnings_exhibit(client, cik, filing)
            published = filing.get("acceptanceDateTime")
            basis = "SEC acceptance datetime UTC; may lag original issuer release"
            if not published:
                # Date-only filings are conservatively available at next calendar day.
                published = (pd.Timestamp(filing["filingDate"]) + pd.Timedelta(days=1)).isoformat() + "Z"
                basis = "No SEC timestamp; conservative next-calendar-day 00:00 UTC"
            record = dict(doc_id=f"sec_{cik}_{accession}", ticker=ticker, company=company["company"],
                          sector=company["sector"], cik=cik, issuer_id=int(company.get("current_snapshot_cik", cik)), published_at=published,
                          publication_date=filing["filingDate"], document_type="SEC_8K_Item2.02_EX99_earnings_release",
                          source_url=source, accession=accession, publication_time_basis=basis)
            record["sec_item_tags"] = filing.get("items", "")
            if accession in source_recovery().get("exhibit_overrides", {}):
                record["document_type"] = "SEC_8K_Item2.02_reviewed_exhibit_earnings_release"
            if filing.get("form") == "6-K":
                record["document_type"] = "SEC_6K_EX99_earnings_release"
            elif "2.02" not in filing.get("items", ""):
                record["document_type"] = "SEC_8K_EX99_earnings_release_reviewed_Item2.01_tag"
            if source.endswith("/" + filing["primaryDocument"]):
                record["document_type"] = "SEC_" + filing.get("form", "8-K").replace("-", "") + "_embedded_earnings_release"
                record["text_scope"] = ("NXP quarterly Reports heading after SEC SIGNATURES block through end of standalone release, including release financial statements; cover and signatures excluded" if cik == 1413447 else "Halliburton explicitly introduced Press Release text through before SIGNATURES; excludes 8-K cover and signature" if cik == 45012 else "Identified embedded press release Attachment I; excludes Attachment II slides")
                if cik == 849395:
                    record["text_scope"] = "CRH results announcement after Form6-K cover and before appended Consolidated Income Statement; management narrative/highlights retained, full interim financial statements and notes excluded"
            elif cik == 1413447 and filing.get("form") == "6-K":
                record["document_type"] = "SEC_6K_reviewed_exhibit_earnings_release"
                record["text_scope"] = "NXP standalone quarterly Reports earnings heading verified; numbered EX-1 or EX-99 release allowed, investor slides and interim reports excluded"
            elif re.search(r"shareholder|letterto.*holder", source, re.I):
                record["document_type"] = "SEC_earnings_shareholder_letter"
                record["text_scope"] = "Substantive earnings shareholder letter; results-availability notice excluded"
            elif source.lower().endswith(".pdf"):
                record["document_type"] = "SEC_earnings_release_or_update_PDF"
                record["text_scope"] = "PDF text layer extracted with pypdf; image-only documents require separate OCR and are not synthesized"
                if hashlib.sha256(content).hexdigest() in source_recovery().get("pdf_pymupdf_overrides", {}):
                    record["text_scope"] = "Reviewed content-SHA-pinned PDF text layer extracted with PyMuPDF; restores earnings narrative omitted by pypdf. No OCR used."
            if filing.get("form") in periodic_rule.get("forms", []):
                record["document_type"] = "SEC_10Q_EX99_reviewed_earnings_release"
                record["text_scope"] = "Standalone issuer quarterly earnings release EX99 attached to 10-Q; whole periodic report excluded; actual SEC acceptance timestamp retained"
            if ticker == "ARE" and re.search(r"supp", source, re.I):
                record["text_scope"] = "Bounded Alexandria earnings press release; starts company Reports heading and ends before Supplemental Information Company Profile when both markers exist"
            if ticker == "FRT":
                record["text_scope"] = "Bounded Federal Realty earnings press release; starts company Announces/Reports heading and ends before separate Summarized/Consolidated Income Statements supplement when both markers exist"
            records.append(save_document(root, record, extract_text(content), scorer))
        except Exception as error:
            failures.append({"ticker": ticker, "cik": cik, "accession": accession, "filing_date": filing["filingDate"], "form": filing.get("form", "8-K"), "stage": "exhibit", "error_category": classify_failure(error), "error": str(error)})
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


def collect_firms(root: Path, client: CachedClient, scorer: TextScorer, universe: pd.DataFrame, start: int, end: int, workers: int = 4, force: bool = False) -> tuple[list, list]:
    """Resume issuer checkpoints; completed means attempted, not 40 quarters available."""
    existing = root / "data/processed/firm_scores.csv"
    prior = pd.read_csv(existing) if existing.exists() else pd.DataFrame()
    records = prior.to_dict("records") if len(prior) else []
    failure_path = root / "data/processed/acquisition_failures.csv"
    failures = pd.read_csv(failure_path).to_dict("records") if failure_path.exists() else []
    checkpoint_dir = root / "data/raw/issuer_checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    status_path = root / "data/processed/issuer_collection_status.csv"
    statuses = {r["ticker"]: r for r in pd.read_csv(status_path).to_dict("records")} if status_path.exists() else {}
    config = json.loads((root/"configs/research.json").read_text(encoding="utf-8"))
    selection_path = root / "data/reference/selected_universe.csv"
    selected = pd.read_csv(selection_path) if selection_path.exists() else universe
    selected = selected[selected.ticker.isin(set(selected.ticker) | set(universe.ticker))]
    started = time.monotonic()
    last_flush = started
    completed_now = 0
    pending = []
    expected_quarters = 4 * (end-start+1)

    def status_for(company, rows, errors, profile=None):
        frame = pd.DataFrame(rows)
        quarters = int(pd.to_datetime(frame.publication_date).dt.to_period("Q").nunique()) if rows else 0
        profile = profile or {}
        forms = profile.get("study_period_forms", {})
        regime = "mixed_8K_6K" if forms.get("8-K") and forms.get("6-K") else "6-K" if forms.get("6-K") else "8-K" if forms.get("8-K") else "no_study_period_filings" if not forms else "other_forms_only"
        submission_errors = [r for r in errors if r.get("stage") == "submissions"]
        state = "submissions_error" if submission_errors else "completed_with_gaps" if rows and quarters < expected_quarters else "completed" if rows else "no_eligible_filings"
        categories = sorted({r.get("error_category") or classify_failure(r.get("error", "")) for r in errors})
        return {"issuer_id": int(company.get("current_snapshot_cik", company["cik"])), "ticker": company["ticker"],
                "company": company["company"], "sector": company["sector"], "cik": int(company["cik"]),
                "status": state, "filing_regime": regime, "candidate_filings": len(rows)+len(errors),
                "documents": len(rows), "failed_candidates": len(errors), "error_category": "|".join(categories),
                "quarters_covered": quarters, "first_publication": frame.publication_date.min() if rows else None,
                "last_publication": frame.publication_date.max() if rows else None,
                "first_study_period_filing": profile.get("study_period_first_filing"),
                "start_year": start, "end_year": end, "updated_at": datetime.now(timezone.utc).isoformat()}

    for company in universe.to_dict("records"):
        ticker = company["ticker"]
        checkpoint = checkpoint_dir / f"{int(company.get('current_snapshot_cik', company['cik']))}_{start}_{end}.json"
        if checkpoint.exists() and not force:
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            if not saved.get("needs_refresh", False):
                records = [r for r in records if r["ticker"] != ticker] + saved["records"]
                failures = [r for r in failures if r["ticker"] != ticker] + saved["failures"]
                statuses[ticker] = saved["status"]
                continue
        # The original audited pilot is a complete checkpoint, not a partial run.
        old_rows = [r for r in records if r["ticker"] == ticker]
        old_errors = [r for r in failures if r["ticker"] == ticker]
        for row in old_rows:
            document_checkpoint = root / "data/raw/document_records" / (row["doc_id"] + ".json")
            text_path = root / "data/raw/text" / (row["doc_id"] + ".txt")
            if not document_checkpoint.exists() and text_path.exists():
                original_text = text_path.read_text(encoding="utf-8")
                if hashlib.sha256(original_text.encode()).hexdigest() == row.get("text_sha256"):
                    # Preserve audited pilot text/score hashes when an issuer is
                    # rechecked for a different missing or incorrect exhibit.
                    write_json_atomic(row, document_checkpoint)
        old_quarters = pd.to_datetime(pd.Series([r["publication_date"] for r in old_rows], dtype="object")).dt.to_period("Q").nunique()
        if not force and ticker in config["pilot_tickers"] and old_quarters == expected_quarters:
            status = status_for(company, old_rows, old_errors, {"study_period_forms": {"8-K": 1}})
            status["checkpoint_origin"] = "audited_33_issuer_pilot"
            statuses[ticker] = status
            write_json_atomic({"status": status, "records": old_rows, "failures": old_errors}, checkpoint)
            continue
        statuses[ticker] = dict(issuer_id=int(company.get("current_snapshot_cik", company["cik"])),
                                ticker=ticker, company=company["company"], sector=company["sector"], cik=int(company["cik"]),
                                status="pending", documents=0, start_year=start, end_year=end,
                                updated_at=datetime.now(timezone.utc).isoformat())
        pending.append((company, checkpoint))

    def flush(force_flush=False):
        nonlocal last_flush
        write_csv_atomic(pd.DataFrame(statuses.values()).sort_values("ticker"), status_path)
        if force_flush or time.monotonic()-last_flush >= 60 or completed_now % 10 == 0:
            if records:
                write_csv_atomic(pd.DataFrame(records).sort_values(["ticker", "published_at"]), existing)
            failure_columns = ["ticker", "cik", "accession", "filing_date", "form", "stage", "error_category", "error"]
            write_csv_atomic(pd.DataFrame(failures).reindex(columns=failure_columns), failure_path)
            coverage_config = dict(config, start_year=start, end_year=end)
            write_coverage(root, selected, coverage_config)
            last_flush = time.monotonic()

    flush(True)
    print(f"START {len(universe)} issuers: {len(universe)-len(pending)} checkpointed, {len(pending)} pending; workers={workers}; global SEC limit={1/client.interval:g}/s", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(collect_company, root, client, scorer, company, start, end): (company, checkpoint) for company, checkpoint in pending}
        for future in as_completed(futures):
            company, checkpoint = futures[future]
            ticker = company["ticker"]
            try:
                rows, errors = future.result()
            except Exception as error:
                rows, errors = [], [{"ticker": ticker, "cik": company["cik"], "stage": "submissions", "error_category": classify_failure(error), "error": str(error)}]
            profile_path = client.cache.parent / "issuer_profiles" / f"{int(company['cik'])}.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
            status = status_for(company, rows, errors, profile)
            statuses[ticker] = status
            write_json_atomic({"status": status, "records": rows, "failures": errors}, checkpoint)
            records = [r for r in records if r["ticker"] != ticker] + rows
            failures = [r for r in failures if r["ticker"] != ticker] + errors
            completed_now += 1
            flush()
            elapsed = time.monotonic()-started
            eta = elapsed/completed_now * (len(pending)-completed_now)
            print(f"PROGRESS {len(universe)-len(pending)+completed_now}/{len(universe)} issuers; {len(records)} documents; elapsed={elapsed/60:.1f}m ETA={eta/60:.1f}m; requests={client.requests_made}", flush=True)
    flush(True)
    return records, failures


def write_manifest(root: Path) -> None:
    frames = []
    for name in ("firm_scores", "fomc_scores"):
        path = root / "data/processed" / (name + ".csv")
        if path.exists():
            frame = pd.read_csv(path, low_memory=False)
            cols = [c for c in ("doc_id", "issuer_id", "cik", "ticker", "company", "sector", "document_type", "text_scope", "published_at", "publication_date", "meeting_date", "source_url", "calendar_source_url", "official_IR_source_url", "official_IR_release_date", "matched_SEC_source_url", "sec_acceptance_at", "pdf_creation_datetime", "pdf_modification_datetime", "publication_time_basis", "text_sha256", "retrieved_at") if c in frame]
            frames.append(frame[cols])
    if frames:
        write_csv_atomic(pd.concat(frames, ignore_index=True),root / "data/processed/source_manifest.csv")


def write_coverage(root: Path, selected: pd.DataFrame, config: dict) -> dict:
    firm_path, fed_path = root/"data/processed/firm_scores.csv", root/"data/processed/fomc_scores.csv"
    firms = pd.read_csv(firm_path, low_memory=False) if firm_path.exists() else pd.DataFrame()
    fed = pd.read_csv(fed_path) if fed_path.exists() else pd.DataFrame()
    failures = pd.read_csv(root/"data/processed/acquisition_failures.csv") if (root/"data/processed/acquisition_failures.csv").exists() else pd.DataFrame()
    status_path = root/"data/processed/issuer_collection_status.csv"
    statuses = pd.read_csv(status_path) if status_path.exists() else pd.DataFrame()
    if len(statuses):
        statuses = statuses[statuses.ticker.isin(selected.ticker)]
    full = len(selected) > len(config.get("pilot_tickers", []))
    attempted = int((~statuses.status.isin(["pending", "running"])).sum()) if len(statuses) else 0
    state = ("full_collection_in_progress" if attempted < len(selected) else "full_collection_attempted_pending_audit") if full else "executed_pilot"
    report = {"status": state, "start_year": config["start_year"], "end_year": config["end_year"],
              "updated_at": datetime.now(timezone.utc).isoformat(), "attempted_companies": attempted,
              "pending_companies": len(selected)-attempted if full else 0,
              "target_companies": len(selected), "covered_companies": int(firms.ticker.nunique()) if len(firms) else 0,
              "missing_companies": sorted(set(selected.ticker) - set(firms.ticker if len(firms) else [])),
              "firm_documents": len(firms), "fomc_documents": len(fed), "failed_acquisitions": len(failures),
              "universe_basis": config["universe_basis"], "sectors": {},
              "limitations": ["Current constituent snapshot and current GICS labels create survivorship and classification bias.",
                "All distinct issuers in the fixed current snapshot are attempted; historical S&P500 membership is not reconstructed." if full else "Pilot companies selected deliberately; not a random or complete S&P500 sample.",
                "Corpus includes SEC Item2.02/6-K earnings releases, substantive shareholder letters and guidance updates; bounded EchoStar and T.Rowe Price exceptions use standalone EX99 releases attached to 10-K/Q. Verified official issuer IR releases/letters restore missing SEC text. Whole reports, standalone slides and independent financial tables are excluded.",
                "IPO, spin-off, foreign-filer and successor-entity histories can leave fewer than 40 publication quarters; full-universe attempt does not imply a balanced panel.",
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
        report["fomc_by_publication_year"] = fed.assign(year=pd.to_datetime(fed.publication_date).dt.year).groupby("year").size().to_dict()
    if len(statuses):
        report["issuer_status_counts"] = statuses.status.value_counts().to_dict()
        report["issuer_regime_counts"] = statuses.filing_regime.fillna("not_yet_examined").value_counts().to_dict() if "filing_regime" in statuses else {}
    write_json_atomic(report, root/"reports/data_coverage.json")
    write_manifest(root)
    return report
