"""Optional executed LM/FinBERT method comparison on matched sentence samples.

This is NOT a predictive-performance comparison or a labeled-accuracy test.
FinBERT neutral probabilities are not interpreted as uncertainty probabilities.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from topbottom.text import TextScorer, SENTENCE, SAFE_HARBOR, TOKEN
from topbottom.data import write_csv_atomic, write_json_atomic


def matched_correlation(frame):
    value = frame[["lm_matched_tone", "finbert_tone"]].rank().corr().iloc[0, 1] if len(frame) > 2 else np.nan
    return float(value) if np.isfinite(value) else None


def compatible_cached_rows(previous, documents, revision, settings_sha256):
    required={"doc_id", "model_revision", "sampling_settings_sha256", "text_sha256"}
    if not required.issubset(previous.columns):
        return pd.DataFrame()
    hashes=documents.set_index("doc_id").text_sha256.to_dict()
    keep=(previous.doc_id.isin(documents.doc_id) & previous.model_revision.eq(revision)
          & previous.sampling_settings_sha256.eq(settings_sha256)
          & previous.apply(lambda row: hashes.get(row.doc_id)==row.text_sha256,axis=1))
    return previous.loc[keep].copy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-sentences", type=int, default=24)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--model", default="ProsusAI/finbert")
    parser.add_argument("--revision", help="Pin a Hugging Face commit SHA; saved in every output row")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--staging-cache", type=Path, help="Write only an ignored private inference cache; do not publish method results")
    parser.add_argument("--resume-cache", type=Path, help="Reuse compatible staged inference after final corpus freeze")
    args = parser.parse_args()
    import torch
    from huggingface_hub import model_info
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    revision = args.revision or model_info(args.model).sha
    cache = ROOT/"models/huggingface"
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=revision, cache_dir=cache)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, revision=revision, cache_dir=cache)
    model.eval()
    if args.download_only:
        print(f"Downloaded {args.model} revision {revision}")
        return
    labels = {str(v).lower(): int(k) for k, v in model.config.id2label.items()}
    if not all(label in labels for label in ("positive", "negative", "neutral")):
        raise ValueError(f"Unexpected model labels: {labels}")
    lm = TextScorer(ROOT)
    import transformers, tokenizers
    settings = dict(version="complete_sentences_v3_settingshashed", max_sentences=args.max_sentences,
                    min_sentence_words=5, max_sentence_words=120, max_wordpieces=256,
                    add_special_tokens=True, sentence_pattern=SENTENCE.pattern,
                    boilerplate_pattern=SAFE_HARBOR.pattern, word_pattern=TOKEN.pattern,
                    sentence_selection="unique numpy linspace integer indices across all eligible sentences",
                    transformers_version=transformers.__version__, tokenizers_version=tokenizers.__version__,
                    lm_lexicon_sha256=hashlib.sha256(json.dumps({k:sorted(v) for k,v in lm.lexicons.items()},sort_keys=True).encode()).hexdigest())
    settings_sha256 = hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()
    firms = pd.read_csv(ROOT/"data/processed/firm_scores.csv", low_memory=False).sort_values("published_at").groupby("ticker").tail(1)
    fed = pd.read_csv(ROOT/"data/processed/fomc_scores.csv")
    fed = fed[fed.meeting_date.str[:4].isin(["2024", "2025"])]
    documents = pd.concat([firms, fed], ignore_index=True)
    output = args.staging_cache or ROOT/"data/processed/finbert_method_sample.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for cache_path in [args.resume_cache, output]:
        if cache_path is None or not cache_path.exists():
            continue
        previous = pd.read_csv(cache_path)
        previous = compatible_cached_rows(previous, documents, revision, settings_sha256)
        rows.extend(previous.to_dict("records"))
    rows = list({row["doc_id"]:row for row in rows}.values())
    current_metadata=documents.set_index("doc_id").to_dict("index")
    for row in rows:
        current=current_metadata[row["doc_id"]]
        row.update({key:current.get(key) for key in ("ticker", "sector", "document_type", "publication_date", "published_at", "sec_acceptance_at", "publication_time_basis", "source_url")})
        row["lm_full_document_tone"]=current["tone"]
    done = {row["doc_id"] for row in rows}
    for record in documents.to_dict("records"):
        if record["doc_id"] in done:
            continue
        text = (ROOT/"data/raw/text"/(record["doc_id"]+".txt")).read_text(encoding="utf-8")
        if hashlib.sha256(text.encode()).hexdigest() != record["text_sha256"]:
            if args.staging_cache:
                print(f"Skipped mutable/noncanonical stage input: {record['doc_id']}",flush=True)
                continue
            raise ValueError(f"Final score input hash mismatch: {record['doc_id']}; run source audit before inference")
        sentences = [s.strip() for s in SENTENCE.split(text) if 5 <= len(TOKEN.findall(s)) <= 120 and not SAFE_HARBOR.search(s)]
        sentences = [s for s in sentences if len(tokenizer.encode(s,add_special_tokens=True,truncation=True,max_length=257)) <= 256]
        if not sentences:
            continue
        ids = np.unique(np.linspace(0, len(sentences)-1, min(args.max_sentences,len(sentences)), dtype=int))
        selected = [sentences[i] for i in ids]
        probabilities = []
        token_lengths = [len(tokenizer.encode(s, add_special_tokens=True)) for s in selected]
        for offset in range(0, len(selected), args.batch_size):
            inputs = tokenizer(selected[offset:offset+args.batch_size], return_tensors="pt", padding=True, truncation=True, max_length=256)
            with torch.inference_mode():
                probabilities.extend(torch.softmax(model(**inputs).logits, dim=-1).numpy().tolist())
        probs = np.asarray(probabilities)
        row = {k: record.get(k) for k in ("doc_id", "ticker", "sector", "document_type", "publication_date", "published_at", "sec_acceptance_at", "publication_time_basis", "source_url")}
        row['text_sha256']=record['text_sha256']
        row.update(sample_sentences=len(selected), sample_max_sentences=args.max_sentences, sampling_version=settings["version"], sampling_settings_sha256=settings_sha256, eligible_sentences=len(sentences),
                   lm_matched_tone=lm.counts(" ".join(selected))["tone"],
                   lm_full_document_tone=record["tone"],
                   finbert_tone=float((probs[:,labels["positive"]]-probs[:,labels["negative"]]).mean()),
                   finbert_positive=float(probs[:,labels["positive"]].mean()),
                   finbert_negative=float(probs[:,labels["negative"]].mean()),
                   finbert_neutral=float(probs[:,labels["neutral"]].mean()),
                   sentences_truncated=sum(length>256 for length in token_lengths),
                   sample_sha256=hashlib.sha256("\n".join(selected).encode()).hexdigest(),
                   model=args.model, model_revision=revision)
        rows.append(row)
        write_csv_atomic(pd.DataFrame(rows), output)
        print(f"FinBERT {len(rows)}/{len(documents)}: {record['doc_id']}",flush=True)
    frame = pd.DataFrame(rows)
    write_csv_atomic(frame, output)
    if args.staging_cache:
        print(f"Private staged inference complete: {len(frame)} documents. Public comparison unchanged.",flush=True)
        return
    by_source = {}
    for document_type, group in frame.groupby("document_type"):
        by_source[document_type] = {"documents":len(group),"matched_spearman":matched_correlation(group)}
    by_corpus = {name: {"documents":len(group), "matched_spearman":matched_correlation(group)}
                 for name, group in frame.groupby(np.where(frame.document_type.eq("FOMC_minutes"), "FOMC", "corporate"))}
    summary = {"status":"executed", "model":args.model,"model_revision":revision,"model_url":"https://huggingface.co/"+args.model,
               "created_at":datetime.now(timezone.utc).isoformat(),"documents":len(frame),
               "companies":int(frame.ticker.nunique()),"sentences":int(frame.sample_sentences.sum()),
               "truncated_sentences":int(frame.sentences_truncated.sum()),
               "lm_finbert_matched_spearman":matched_correlation(frame),
               "by_source":by_source, "by_corpus":by_corpus,
               "sampling":f"Latest collected release per company, FOMC meetings 2024-2025; up to {args.max_sentences} evenly spaced eligible sentences per document",
               "limitation":"Agreement between methods only. No human gold labels; not classification accuracy or return predictability. FinBERT neutral is not uncertainty.",
               "full_corpus_finbert_executed":False}
    summary["sampling_settings"]=settings
    summary["sampling_settings_sha256"]=settings_sha256
    write_json_atomic(summary, ROOT/"reports/finbert_method_comparison.json")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__": main()
