"""Rescore locally cached documents without making network requests."""
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from topbottom.text import TextScorer
from topbottom.data import write_manifest, write_csv_atomic

def main():
    scorer = TextScorer(ROOT)
    for name in ("firm_scores", "fomc_scores"):
        path = ROOT/"data/processed"/(name+".csv")
        if not path.exists(): continue
        rows = []
        for row in pd.read_csv(path).to_dict("records"):
            raw = ROOT/"data/raw/text"/(row["doc_id"]+".txt")
            row.update(scorer.score(raw.read_text(encoding="utf-8")))
            row['scored_at'] = datetime.now(timezone.utc).isoformat()
            rows.append(row)
        write_csv_atomic(pd.DataFrame(rows),path)
        print(f"Rescored {len(rows)} {name} documents")
    write_manifest(ROOT)

if __name__ == "__main__": main()
