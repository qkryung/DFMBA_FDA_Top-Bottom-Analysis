"""Transparent financial-language scoring; no fitted model or FinBERT claims."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

TOKEN = re.compile(r"\b[A-Za-z]+(?:'[A-Za-z]+)?\b")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])|\n+")
FORWARD = re.compile(r"\b(expect\w*|anticipat\w*|outlook|guidance|forecast\w*|project\w*|will|plan\w*|future|next quarter|next year)\b", re.I)
SAFE_HARBOR = re.compile(r"forward[- ]looking statements?|safe harbor|actual results.{0,80}differ|risks and uncertainties|no obligation to update|undue reliance", re.I)


class TextScorer:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lexicons = {}
        for label in ("positive", "negative", "uncertainty"):
            path = self.root / "data/raw/dictionaries" / f"LoughranMcDonald_{label.title()}.csv"
            if not path.exists():
                raise FileNotFoundError(f"Missing LM dictionary: {path.name}; run collect_data.py --dictionary-zip PATH")
            self.lexicons[label] = {w.strip().upper() for w in path.read_text(encoding="utf-8-sig").splitlines() if w.strip()}
        topics = json.loads((self.root / "configs/topics.json").read_text(encoding="utf-8"))
        self.topics = {name: re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.I) for name, words in topics.items()}

    def counts(self, text: str) -> dict:
        tokens = [t.upper() for t in TOKEN.findall(text)]
        result = {label: sum(token in words for token in tokens) for label, words in self.lexicons.items()}
        n = len(tokens)
        result.update(word_count=n, tone=100 * (result["positive"] - result["negative"]) / n if n else None,
                      uncertainty_rate=100 * result["uncertainty"] / n if n else None)
        return result

    def score(self, text: str) -> dict:
        # Boilerplate exclusion operates at sentence level. This is a heuristic,
        # not an assurance that all legal language has been removed.
        raw_sentences = [s.strip() for s in SENTENCE.split(text) if len(TOKEN.findall(s)) >= 5]
        sentences = [s for s in raw_sentences if not SAFE_HARBOR.search(s)]
        result = self.counts(" ".join(sentences))
        result.update(sentence_count=len(sentences), excluded_boilerplate_sentences=len(raw_sentences)-len(sentences),
                      sentiment_method="LM_20200204_dictionary", text_sha256=hashlib.sha256(text.encode()).hexdigest())
        forward = [s for s in sentences if FORWARD.search(s)]
        fscore = self.counts(" ".join(forward))
        result["forward_sentence_count"] = len(forward)
        result["forward_tone"] = fscore["tone"]
        result["forward_uncertainty_rate"] = fscore["uncertainty_rate"]
        for topic, pattern in self.topics.items():
            matched = [s for s in sentences if pattern.search(s)]
            ts = self.counts(" ".join(matched))
            result[f"topic_{topic}_sentences"] = len(matched)
            result[f"topic_{topic}_share"] = len(matched) / len(sentences) if sentences else None
            for k in ("tone", "word_count", "positive", "negative", "uncertainty", "uncertainty_rate"):
                result[f"topic_{topic}_{k}"] = ts[k]
        return result
