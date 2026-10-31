"""Rescore locally cached documents without network requests.

--changed-only canonicalizes input hashes after legacy CRLF storage, preserving
unchanged document scores and timestamps. It records whether any numeric score
changed; the initial pilot already used the same universal-newline read policy.
"""
import argparse
import hashlib
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from topbottom.text import TextScorer
from topbottom.data import write_manifest, write_csv_atomic, write_json_atomic

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-only",action="store_true")
    args=parser.parse_args()
    scorer = TextScorer(ROOT)
    audited=[]
    for name in ("firm_scores", "fomc_scores"):
        path = ROOT/"data/processed"/(name+".csv")
        if not path.exists(): continue
        rows=[]; changed=0
        for row in pd.read_csv(path).to_dict("records"):
            raw=ROOT/"data/raw/text"/(row["doc_id"]+".txt")
            text=raw.read_text(encoding="utf-8")
            digest=hashlib.sha256(text.encode()).hexdigest()
            if args.changed_only and digest==row.get("text_sha256"):
                rows.append(row);continue
            scores=scorer.score(text)
            differences=[]
            for key,value in scores.items():
                if key in ["text_sha256","sentiment_method"]:continue
                old=row.get(key)
                if pd.isna(value) and pd.isna(old):continue
                if isinstance(value,(int,float)) and isinstance(old,(int,float)) and math.isclose(value,old,rel_tol=1e-12,abs_tol=1e-12):continue
                if value!=old:differences.append(key)
            if digest!=row.get("text_sha256"):
                audited.append(dict(doc_id=row["doc_id"],ticker=row.get("ticker"),old_text_sha256=row.get("text_sha256"),new_text_sha256=digest,numeric_fields_changed=differences))
            raw.write_text(text,encoding="utf-8",newline="\n")
            row.update(scores);row["scored_at"]=datetime.now(timezone.utc).isoformat()
            write_json_atomic(row,ROOT/"data/raw/document_records"/(row["doc_id"]+".json"))
            rows.append(row);changed+=1
        write_csv_atomic(pd.DataFrame(rows),path)
        print(f"Rescored {changed}/{len(rows)} {name} documents",flush=True)
    write_json_atomic({"input_policy":"UTF-8 text after universal newline normalization to LF, before sentence-level boilerplate exclusion", "changed_inputs":len(audited),"documents_with_numeric_changes":sum(bool(r["numeric_fields_changed"]) for r in audited),"records":audited},ROOT/"reports/text_normalization_audit.json")
    write_manifest(ROOT)

if __name__ == "__main__": main()
