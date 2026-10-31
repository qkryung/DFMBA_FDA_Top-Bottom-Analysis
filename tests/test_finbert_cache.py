"""Inference reuse must follow the exact source text and sampling configuration."""
import unittest
import pandas as pd
from scripts.score_finbert_sample import compatible_cached_rows


class FinbertCacheRegression(unittest.TestCase):
    def test_changed_source_settings_or_model_cannot_reuse_old_prediction(self):
        docs=pd.DataFrame([dict(doc_id="release",text_sha256="current-text")])
        valid=dict(doc_id="release",text_sha256="current-text",model_revision="pinned",sampling_settings_sha256="settings")
        candidates=pd.DataFrame([valid,dict(valid,text_sha256="old-wrong-exhibit"),
                                 dict(valid,sampling_settings_sha256="different-tokenization"),
                                 dict(valid,model_revision="other-model")])
        matched=compatible_cached_rows(candidates,docs,"pinned","settings")
        self.assertEqual(len(matched),1)
        self.assertEqual(matched.iloc[0].text_sha256,"current-text")
        self.assertTrue(compatible_cached_rows(candidates.drop(columns="sampling_settings_sha256"),docs,"pinned","settings").empty)


if __name__ == "__main__":
    unittest.main()
