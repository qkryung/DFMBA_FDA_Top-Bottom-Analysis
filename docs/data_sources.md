# Data sources and scoring contract

## Executed scope

The executed research sample is a deliberately selected 33-company pilot: three current S&P 500 issuers in each of 11 current GICS sectors, with SEC filings dated 2016–2025. It is not the full historical S&P 500. The proposal can extend the period and universe. `reports/data_coverage.json` gives the final observed counts; `data/processed/source_manifest.csv` identifies every scored source document.

The current constituent/GICS snapshot is obtained from the [datasets S&P 500 repository](https://github.com/datasets/s-and-p-500-companies). Current membership and sector labels introduce survivorship and classification bias. `data/reference/universe_snapshot.csv` preserves that snapshot; `selected_universe.csv` records the research selection. Different share classes of an issuer are not counted as independent text documents.

## Corporate sources

The frozen pilot contains **1,334 corporate documents**, covering all 40 publication-calendar quarters for each of the 33 firms (1,320 company-quarter cells). Source selection rejected 72 inappropriate exhibits: 49 filings were recovered using the correct alternative exhibit, while 23 filings were excluded entirely. `excluded_exhibits.csv` preserves the source URLs and reasons; a rejected exhibit can share a filing ID with a retained replacement exhibit. All 1,334 retained SEC timestamps were cross-checked against the filing index's Eastern-time acceptance timestamp, with zero discrepancies.

- [SEC submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): current and historical filing indexes.
- SEC 8-K Item 2.02, with substantive earnings-results EX-99 exhibits in HTML. These are issuer earnings releases, **not earnings-call transcripts**. Item 2.02 can include preliminary results or updates; there may be more than four documents in a company-year.
- The file index determines the exhibit URL. Revised annual/quarterly reports and transaction pro-forma statements are excluded by documented rules, with an exclusion ledger. Failed or unsupported exhibits are logged; no text is fabricated to fill gaps.
- `published_at` uses the SEC acceptance datetime in UTC. It can occur after an issuer's original release and is therefore conservative for availability. If a timestamp is missing, next calendar-day 00:00 UTC is used and labeled in `publication_time_basis`.
- The current snapshot gives Exxon Mobil a successor CIK starting in 2026. `configs/research.json` explicitly maps XOM to legacy CIK 34088 for the 2016–2025 study; the SEC submissions JSON is the mapping evidence. Other historical reorganizations require additional mapping when the universe expands.

- Disney requires **two CIKs**: legacy 1001039 through March 19, 2019, then 1744489. `additional_historical_ciks` in the research configuration makes this join reproducible.
- Two IBM releases in 2016 were embedded in 8-K **Attachment I**. The extractor retains the identified press release and stops before Attachment II slides. They carry a distinct document-type label.
- The February 1, 2019 SPG filing is incorrectly tagged as Item 2.01 in the submissions index, although its 8-K body states Item 2.02 and attaches the earnings release. A reviewed accession override is recorded in the configuration.
- Exhibit number alone does not determine source quality. PLD places the earnings release in EX-99.2 and statistical supplements in EX-99.1; some early JNJ releases use suffixes such as EX-99.15. The collector checks candidate content and tries alternative exhibits before logging a candidate as unusable. Standalone financial tables and statistics supplements are not treated as management sentiment.

## FOMC sources

- [Federal Reserve historical calendars](https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm) and [recent calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm).
- The collector discovers actual minutes-document links and their release dates. It does not manufacture eight observations per year. A document can cover more than one meeting or emergency call.
- `meeting_date` is the date encoded in the official minutes URL. Availability uses the **actual minutes release date**, at the standard 14:00 Eastern release time converted to UTC, rather than the meeting date.
- To compare economic assessments consistently, the scored text starts at “Staff Review of the Economic Situation” and ends immediately before “Committee Policy Action.” It includes staff review/outlook and participants' views; it excludes attendee lists, annual administrative material and the repeated formal policy directive.
- The 80-document corpus is defined by **meeting years 2016–2025**. Its actual release dates span February 17, 2016 through December 30, 2025; the final document covers the December 10, 2025 meeting. All dates remain in the manifest; the investment panel uses actual release dates and selects only releases available before each quarter-end cutoff. Collecting 80 documents does not create 80 quarterly investment observations: there are 40 formation quarters, with one latest available minutes document per quarter.

## Market data and quarterly alignment

The executed return analysis uses the authorized local classroom CRSP CIZ monthly file (`MthRet`, decimal total returns) and the local Ken French monthly factor file. The market benchmark is `Mkt−RF + RF`, divided by 100 to convert percentages to decimal returns. This is the broad US equity-market benchmark, **not an S&P 500 index return and not factor alpha**.

The importer maps each selected current ticker to its latest observed PERMNO, then retrieves the continuous PERMNO history, including earlier ticker names. Identical security-month rows are deduplicated and counted; conflicting duplicate keys fail validation. Mapping details and security-level returns stay in `data/private`. Public reports retain source filenames, SHA-256 hashes, coverage and duplicate counts only.

Formation occurs quarterly. Its information cutoff is 00:00 UTC on the final CRSP trading date of March, June, September and December. Disclosures on that date are excluded. Entry is assumed at that date's closing price, followed by the next three complete calendar months. The latest corporate release must be at most 120 days old. Momentum uses three completed months ending **one month before entry**, avoiding the unobserved entry-month close.

Each stock and benchmark requires all three monthly returns. A missing month produces a missing outcome, not a shorter holding period or zero return. The target is stock three-month compounded return minus benchmark three-month compounded return. CRSP ends in December 2025, so the December 2025 formation can have a forecast but no evaluated next-quarter return. Public coverage reports distinguish forecast periods from evaluated OOS periods.

Expanding OOS ridge models require at least 12 matured training quarters and 100 observed company-quarter outcomes. A training outcome's end date must be strictly before the test formation date. Imputation and scaling are fitted inside each training fold. Sector-conditioned macro features avoid treating one common FOMC score as a cross-sectional stock ranking. `docs/research_plan.md` specifies common controls, ablation, quarterly IC, text lead-lag and transaction-cost conventions.

## LM text scores

The executed baseline uses the local course archive `Dictionaries20200204.zip`, containing actual Loughran–McDonald positive, negative and uncertainty dictionaries. The dictionaries themselves are not redistributed. `data/reference/dictionary_manifest.json` records each dictionary's SHA-256 and size. See the [official LM dictionary page](https://sraf.nd.edu/loughranmcdonald-master-dictionary/) for source and use terms.

`tone = 100 × (positive token count − negative token count) / alphabetic token count`.

`uncertainty_rate = 100 × uncertainty token count / alphabetic token count`.

The splitter removes a small set of legal-boilerplate sentences. “Forward” sentences match a prespecified expression for expectations, outlook, guidance or plans. These are transparent heuristics, not validated semantic labels. The dictionary method does not model negation or distinguish every economic meaning of a word.

Five overlapping sentence topics—`inflation`, `employment`, `growth`, `investment`, `rates`—are specified in `configs/topics.json`. A sentence can match several topics. Topic shares therefore do not necessarily sum to one. When no sentence matches, its topic tone is missing (`NaN`), not neutral zero. General affect is **not** the economic direction of inflation, employment or policy, nor an estimate of causal sensitivity.

## Score table columns

| Columns | Meaning |
|---|---|
| `doc_id`, `source_url`, `text_sha256` | Document identity, original evidence and extracted-input-text fingerprint, before sentence-level boilerplate exclusion |
| `ticker`, `company`, `sector`, `cik` | Corporate identity and current GICS sector; absent for FOMC |
| `published_at`, `publication_date`, `publication_time_basis` | Availability timestamp, source filing/release date and timing rule |
| `word_count`, `sentence_count`, `positive`, `negative`, `uncertainty` | Scored corpus sizes and dictionary token counts |
| `tone`, `uncertainty_rate` | Percentage-point lexical rates |
| `forward_tone`, `forward_sentence_count` | Heuristic forward-looking subset |
| `topic_{name}_{tone,word_count,positive,negative,uncertainty,uncertainty_rate,sentences,share}` | Common-topic counts, rates and sentence coverage |
| `sentiment_method`, `retrieved_at` | Method/version and collection timestamp |

## Optional FinBERT comparison

`scripts/score_finbert_sample.py` uses [ProsusAI/finbert](https://huggingface.co/ProsusAI/finbert), with its model commit recorded in the output. The executed sample consists of the latest collected release per company and FOMC minutes for 2024–2025, using up to 24 evenly spaced eligible sentences per document. LM and FinBERT see the same sampled text. LM aggregates lexical counts; FinBERT averages sentence probabilities and reports `P(positive) − P(negative)`.

This checks method agreement on a small matched sample. It does not measure classification accuracy, does not replace human validation, and does not establish which method predicts returns better. FinBERT's **neutral** class is not an uncertainty class. The full-corpus backtest uses LM unless a later explicitly labeled experiment is run.

Use the observed counts and pinned revision in `reports/finbert_method_comparison.json` for the executed sample; the targeted sample size can change as corpus collection completes. Its sampled-sentence LM score is distinct from the full-text LM score used in the return analysis. Neither method's agreement with the other is a ground-truth accuracy measure.

## Reproduction

```powershell
# Use an actual researcher name and contact address; never commit this value.
$env:SEC_USER_AGENT = 'YOUR ACTUAL NAME YOUR CONTACT EMAIL'
python scripts/collect_data.py --dictionary-zip PATH_TO_AUTHORIZED_COURSE_DICTIONARY_ZIP --scope pilot
python scripts/audit_corpus.py
python scripts/score_text.py

# Expand collection, retaining the same documented universe limitations.
python scripts/collect_data.py --scope full
python scripts/audit_corpus.py

# Optional method comparison; requires requirements-finbert.txt.
python scripts/score_finbert_sample.py --revision 0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031
```

The HTTP and text caches, dictionaries, model weights and private market-data files remain local and are excluded from Git. Requests use a shared four-per-second SEC limiter within one collector; avoid starting multiple full collectors concurrently. Repeated collection reuses the HTTP cache. Review newly acquired scope before interpreting analysis results.
