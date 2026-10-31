# Data sources and scoring contract

## Executed scope

The full collection targets all **500 distinct issuers / 503 share classes** in the frozen current constituent snapshot, with SEC filings dated 2016–2025 and all 11 current GICS sectors. This is not the full historical S&P 500. `reports/data_coverage.json` gives collection status and observed counts; `reports/results.json` separately records attempted, document-covered, market-matched and analyzed issuers. `data/processed/source_manifest.csv` identifies every scored source document. The original 33-company pilot remains available in `reports/pilot_baseline.json` and its Git tag.

The current constituent/GICS snapshot is obtained from the [datasets S&P 500 repository](https://github.com/datasets/s-and-p-500-companies). Current membership and sector labels introduce survivorship and classification bias. `data/reference/universe_snapshot.csv` preserves that snapshot; `selected_universe.csv` records the research selection. Different share classes of an issuer are not counted as independent text documents.

## Corporate sources

The preserved 33-company pilot contained 1,334 corporate documents. The final full-run counts and timestamp-audit results supersede those counts in the current reports; the pilot counts must not be interpreted as full-run coverage. `excluded_exhibits.csv` preserves source URLs and exclusion reasons; a rejected exhibit can share a filing ID with a retained replacement exhibit. The audit compares retained SEC acceptance timestamps with the filing index's Eastern-time timestamps.

- [SEC submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): current and historical filing indexes.
- SEC 8-K Item 2.02, with substantive earnings-results EX-99 exhibits in HTML. These are issuer earnings releases, **not earnings-call transcripts**. Item 2.02 can include preliminary results or updates; there may be more than four documents in a company-year.
- Foreign private issuers may furnish comparable earnings releases on Form 6-K. The full collector examines their candidate attachments and applies an explicit earnings-narrative requirement; generic 6-K disclosures are not automatically treated as earnings releases. Unsupported document formats and failed candidates remain visible in the acquisition ledger.
- The full corpus can include official earnings shareholder letters or earnings updates when those attachments carry the substantive results discussion. A short announcement is not preferred over its substantive attached letter. PDF fallbacks use the document's text layer and the same content checks; image-only PDFs are not silently converted to text or filled with invented content. Formats and reviewed extraction scopes remain identifiable in the source metadata.
- Reviewed issuer-specific recovery can use an identifiable release embedded in an 8-K, an earnings-release attachment to another SEC form, or matching text on the issuer's official IR site. It never substitutes a full annual report for an earnings release. For example, EOG releases whose narrative is embedded as images in EDGAR are matched to official IR text. The original SEC accession and acceptance timestamp remain separately attached; the analysis uses the conservative IR availability rule below. The manifest records the actual text source and extraction scope, and `configs/source_recovery.json` and `reports/corpus_repairs_full.json` retain the exceptions.
- The file index determines the exhibit URL. Revised annual/quarterly reports and transaction pro-forma statements are excluded by documented rules, with an exclusion ledger. Failed or unsupported exhibits are logged; no text is fabricated to fill gaps.
- For SEC-hosted text, `published_at` uses the SEC acceptance datetime in UTC. It can occur after an issuer's original release. If a timestamp is missing, next calendar-day 00:00 UTC is used and labeled in `publication_time_basis`.
- For a reviewed official IR replacement with a date but no confirmed intraday publication time, analysis availability is the later of the original SEC acceptance and 00:00 America/New_York on the day after the IR release date, converted to UTC with daylight saving time. The original SEC time and IR date remain separately recorded. PDF creation metadata is a timing consistency check, not proof of publication. Suspected later revisions are excluded unless contemporaneous text can be verified.
- The current snapshot gives Exxon Mobil a successor CIK starting in 2026. `configs/research.json` explicitly maps XOM to legacy CIK 34088 for the 2016–2025 study; the SEC submissions JSON is the mapping evidence. Other reviewed historical reorganizations have bounded predecessor-CIK mappings and official evidence in the configuration. A merger target's separate historical documents are not automatically combined with the surviving issuer.

- Disney requires **two CIKs**: legacy 1001039 through March 19, 2019, then 1744489. `additional_historical_ciks` in the research configuration makes this join reproducible.
- Two IBM releases in 2016 were embedded in 8-K **Attachment I**. The extractor retains the identified press release and stops before Attachment II slides. They carry a distinct document-type label.
- The February 1, 2019 SPG filing is incorrectly tagged as Item 2.01 in the submissions index, although its 8-K body states Item 2.02 and attaches the earnings release. A reviewed accession override is recorded in the configuration.
- Exhibit number alone does not determine source quality. PLD places the earnings release in EX-99.2 and statistical supplements in EX-99.1; some early JNJ releases use suffixes such as EX-99.15. The collector checks candidate content and tries alternative exhibits before logging a candidate as unusable. Standalone financial tables and statistics supplements are not treated as management sentiment.

## FOMC sources

- [Federal Reserve historical calendars](https://www.federalreserve.gov/monetarypolicy/fomc_historical.htm) and [recent calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm).
- The collector discovers actual minutes-document links and their release dates. It does not manufacture eight observations per year. A document can cover more than one meeting or emergency call.
- `meeting_date` is the date encoded in the official minutes URL. Availability uses the **actual minutes release date**, at the standard 14:00 Eastern release time converted to UTC, rather than the meeting date.
- To compare economic assessments consistently, the scored text starts at “Staff Review of the Economic Situation” and ends immediately before “Committee Policy Action.” It includes staff review/outlook and participants' views; it excludes attendee lists, annual administrative material and the repeated formal policy directive.
- The final corpus uses **release dates during 2016–2025**, yielding 81 minutes documents. This includes the December 2015 meeting minutes [released January 6, 2016](https://www.federalreserve.gov/newsevents/pressreleases/monetary20160106a.htm), which were absent from the original 80-document pilot that began its calendar search in meeting year 2016. The existing 80 scores are preserved; the added document does not replace the February 17, 2016 latest-available document at the first quarterly formation. The final document covers the December 10, 2025 meeting and was released December 30. The collector searches the previous meeting-year archive before filtering by actual release date. The investment panel still has 40 formation quarters with one latest available minutes document per quarter; document count is not an independent quarterly sample size.

## Market data and quarterly alignment

The executed return analysis uses the authorized local classroom CRSP CIZ monthly file (`MthRet`, decimal total returns) and the local Ken French monthly factor file. The market benchmark is `Mkt−RF + RF`, divided by 100 to convert percentages to decimal returns. This is the broad US equity-market benchmark, **not an S&P 500 index return and not factor alpha**.

The importer checks ticker candidates against the study endpoint, issuer names and share classes, then retrieves the matched security's history, including earlier ticker names. A current symbol alone is insufficient: an old symbol may have belonged to a different company or a fund. Reviewed changes and new spin-offs are documented in [issuer identity review](issuer_identity_review.md) and the mapping configuration. Unsupported or ambiguous identities are excluded rather than assigned another entity's return. Identical security-month rows are deduplicated and counted; conflicting duplicate keys fail validation. PERMNO mappings and security-level returns stay in `data/private`. Public reports retain source filenames, SHA-256 hashes, coverage, match reasons and duplicate counts without private security identifiers.

Formation occurs quarterly. Its information cutoff is 00:00 UTC on the final CRSP trading date of March, June, September and December. Disclosures on that date are excluded. Entry is assumed at that date's closing price, followed by the next three complete calendar months. The latest corporate release must be at most 120 days old. Momentum uses three completed months ending **one month before entry**, avoiding the unobserved entry-month close.

Each stock and benchmark requires all three monthly returns. A missing month produces a missing outcome, not a shorter holding period or zero return. The target is stock three-month compounded return minus benchmark three-month compounded return. CRSP ends in December 2025, so the December 2025 formation can have a forecast but no evaluated next-quarter return. Public coverage reports distinguish forecast periods from evaluated OOS periods.

Expanding OOS ridge models require at least 12 matured training quarters and 100 observed company-quarter outcomes. A training outcome's end date must be strictly before the test formation date. Imputation and scaling are fitted inside each training fold. Sector-conditioned macro features avoid treating one common FOMC score as a cross-sectional stock ranking. `docs/research_plan.md` specifies common controls, ablation, quarterly IC, text lead-lag and transaction-cost conventions.

## LM text scores

The executed baseline uses the local course archive `Dictionaries20200204.zip`, containing actual Loughran–McDonald positive, negative and uncertainty dictionaries. The dictionaries themselves are not redistributed. `data/reference/dictionary_manifest.json` records each dictionary's SHA-256 and size. See the [official LM dictionary page](https://sraf.nd.edu/loughranmcdonald-master-dictionary/) for source and use terms.

The same fixed archive and text-processing rules are applied across the historical study window. We have not reconstructed the dictionary/model version available at every historical date; `20200204` identifies the supplied archive, not a verified official annual dictionary release. Document availability checks and train-only parameter estimation should not be read as a full historical software-deployment reconstruction.

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
python scripts/collect_data.py --dictionary-zip PATH_TO_AUTHORIZED_COURSE_DICTIONARY_ZIP --scope full
python scripts/recover_corpus.py
python scripts/finalize_source_repairs.py
python scripts/score_text.py --changed-only
python scripts/audit_corpus.py

# Resume checkpoints, retaining the same fixed universe.
python scripts/collect_data.py --scope full
python scripts/recover_corpus.py
python scripts/finalize_source_repairs.py
python scripts/score_text.py --changed-only
python scripts/audit_corpus.py

# Optional method comparison; requires requirements-finbert.txt.
python scripts/score_finbert_sample.py --revision 0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031
```

The HTTP and text caches, dictionaries, model weights and private market-data files remain local and are excluded from Git. The full run uses one shared SEC limiter configured at at most eight requests per second, below the [SEC's stated ten-per-second user limit](https://www.sec.gov/about/developer-resources), with backoff and a reduced rate on throttling responses. Avoid starting multiple collectors concurrently. Repeated collection reuses HTTP, document and issuer checkpoints; the source snapshot is refreshed only with an explicit option. Review newly acquired scope before interpreting analysis results.

The fixed comparison settings are recorded in `reports/full_run_protocol.json` before full-universe model outputs were observed. This is a project execution record, not external preregistration. The expanded sample overlaps the pilot; it is not an independent holdout replication. The fixed ridge penalty uses unnormalized squared errors, so increasing the number of training rows reduces its relative shrinkage. Do not attribute all pilot/full differences solely to representativeness.
