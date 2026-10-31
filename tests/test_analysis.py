"""Economic/data boundary tests, independent of externally downloaded files."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from topbottom.analysis import (TOPICS, build_panel, compound_exact, expanding_predictions,
    feature_frame, normalize_scores, portfolio_series, require_unique, ridge_predict,
    signal_validity, disagreement_analysis)
from topbottom.analysis import prepare_market


def document(doc_id, timestamp, tone=1., ticker=None):
    row = {"doc_id": doc_id, "published_at": timestamp, "tone": tone,
           "uncertainty": 2, "word_count": 100, "forward_tone": .2,
           "forward_sentence_count": 2, "sector": "Information Technology"}
    if ticker:
        row["ticker"] = ticker
    for topic in TOPICS:
        row[f"topic_{topic}_tone"] = .5
        row[f"topic_{topic}_share"] = .1
    return row


def synthetic_panel(periods=18, firms=12):
    """Deterministic generated observations used only for software tests."""
    rows=[]
    for q in range(periods):
        p = pd.Period("2016-03",freq="M")+3*q
        for i in range(firms):
            row = {"ticker": f"T{i}", "sector": "Information Technology" if i%2 else "Industrials",
                   "formation_date": p.end_time.strftime("%Y-%m-%d"),
                   "label_end": (p+3).end_time.strftime("%Y-%m-%d"),
                   "excess_return": .01*np.sin(i+q), "stock_return": .01*np.sin(i+q)+.02,
                   "market_return": .02, "momentum": .01*np.cos(i+q)}
            for source in ("bu","td"):
                row[f"{source}_tone"] = np.sin(q+i) if source=="bu" else np.sin(q)
                row[f"{source}_uncertainty_rate"] = .1+.01*i if source=="bu" else .3
                row[f"{source}_forward_tone"] = .2
                for topic in TOPICS:
                    row[f"{source}_topic_{topic}_tone"] = np.cos(q+i) if source=="bu" else np.cos(q)
            rows.append(row)
    return pd.DataFrame(rows)


class PointInTimeTests(unittest.TestCase):
    def test_sec_and_official_ir_iso_timestamps_keep_exact_availability(self):
        rows = pd.DataFrame([
            document("sec", "2024-03-27T20:01:02.000Z", ticker="AAA"),
            document("ir", "2024-03-28T04:00:00+00:00", ticker="AAA"),
        ])
        parsed = normalize_scores(rows).set_index("doc_id")
        self.assertEqual(parsed.loc["sec", "published_at"], pd.Timestamp("2024-03-27T20:01:02Z"))
        self.assertEqual(parsed.loc["ir", "published_at"], pd.Timestamp("2024-03-28T04:00:00Z"))
        self.assertGreater(parsed.loc["ir", "published_at"], parsed.loc["sec", "published_at"])

    def test_permno_history_recovers_old_ticker_and_deduplicates_identical_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=pd.DataFrame({"PERMNO":[1,1,1],"Ticker":["OLD","NEW","NEW"],
                                 "MthCalDt":["2024-01-31","2024-02-29","2024-02-29"],
                                 "MthRet":[.1,.2,.2],"MthPrc":[100,110,110],"ShrOut":[1000,1000,1000]})
            source.to_csv(root/"crsp.csv",index=False)
            (root/"ff.csv").write_text("Header\n,Mkt-RF,SMB,HML,RF\n202401,1,2,3,0.1\n202402,2,3,4,0.2\n2024,12,1,2,1\n",encoding="utf-8")
            manifest=prepare_market(root/"crsp.csv",root/"ff.csv",["NEW"],root/"out")
            returns=pd.read_csv(root/"out/monthly_returns.csv")
            factors=pd.read_csv(root/"out/market_factors.csv")
            self.assertEqual(len(returns),2)
            self.assertEqual(set(returns.ticker),{"NEW"})
            self.assertEqual(manifest["exact_duplicate_rows_removed"],1)
            self.assertEqual(len(factors),2)
            self.assertAlmostEqual(factors.iloc[0].market_return,.011)

    def test_release_on_entry_day_and_future_fomc_excluded(self):
        firms = pd.DataFrame([document("old","2024-03-01T20:00:00Z",1.,"AAA"),
                              document("same-day","2024-03-28T13:00:00Z",99.,"AAA")])
        fomc = pd.DataFrame([document("known","2024-02-21T19:00:00Z",2.),
                            document("future","2024-04-01T18:00:00Z",99.)])
        market = pd.DataFrame({"ticker":["AAA"]*4,"date":["2024-03-28","2024-04-30","2024-05-31","2024-06-28"],"month":["2024-03","2024-04","2024-05","2024-06"],"return":[0,.1,.2,-.1]})
        factors = pd.DataFrame({"month":market.month,"market_return":[0,.01,.02,.03]})
        panel,_ = build_panel(firms,fomc,market,factors)
        first = panel.iloc[0]
        self.assertEqual(first.firm_doc_id,"old")
        self.assertEqual(first.fomc_doc_id,"known")
        self.assertAlmostEqual(first.excess_return,1.1*1.2*.9-1.01*1.02*1.03)

    def test_incomplete_horizon_is_missing_not_shorter_compound(self):
        monthly=pd.DataFrame({"month":["2024-04","2024-06"],"return":[.1,.2]})
        self.assertTrue(np.isnan(compound_exact(monthly,["2024-04","2024-05","2024-06"],"return")))

    def test_momentum_excludes_unobserved_entry_month_close(self):
        firms=pd.DataFrame([document("firm","2024-03-01T00:00:00Z",ticker="AAA")])
        fomc=pd.DataFrame([document("fed","2024-02-01T00:00:00Z")])
        months=["2023-12","2024-01","2024-02","2024-03","2024-04","2024-05","2024-06"]
        monthly=pd.DataFrame({"ticker":"AAA","month":months,"date":["2023-12-29","2024-01-31","2024-02-29","2024-03-28","2024-04-30","2024-05-31","2024-06-28"],"return":[.1,.2,.3,999.,0.,0.,0.]})
        factors=pd.DataFrame({"month":months,"market_return":0.})
        panel,_=build_panel(firms,fomc,monthly,factors)
        self.assertAlmostEqual(panel.iloc[0].momentum,1.1*1.2*1.3-1)

    def test_duplicate_join_grain_fails(self):
        with self.assertRaises(ValueError):
            require_unique(pd.DataFrame({"ticker":["A","A"],"month":["2024-01"]*2}),["ticker","month"],"test")

    def test_unmentioned_topic_is_missing(self):
        doc=document("d","2024-01-01T00:00:00Z",ticker="A")
        doc["topic_inflation_share"]=0
        doc["topic_inflation_tone"]=0
        normalized=normalize_scores(pd.DataFrame([doc]))
        self.assertTrue(np.isnan(normalized.loc[0,"topic_inflation_tone"]))
        self.assertEqual(normalized.loc[0,"uncertainty_rate"],2.)

    def test_training_never_includes_unmatured_outcome(self):
        panel=synthetic_panel()
        predictions,folds=expanding_predictions(panel,min_train_periods=3,min_train_rows=20)
        self.assertGreater(len(predictions),0)
        for fold in folds:
            self.assertLess(fold["latest_label_end"],fold["test_date"])
        # Mutating outcomes from first test onward must not alter first predictions.
        first=folds[0]["test_date"]
        modified=panel.copy()
        modified.loc[modified.formation_date>=first,"excess_return"]=999
        changed,_=expanding_predictions(modified,min_train_periods=3,min_train_rows=20)
        np.testing.assert_allclose(predictions.loc[predictions.formation_date.eq(first),"prediction"],changed.loc[changed.formation_date.eq(first),"prediction"])

    def test_scaler_and_imputer_do_not_fit_test_rows(self):
        train=pd.DataFrame({"x":[1.,2.,3.,np.nan],"z":[0.,1.,0.,1.]})
        y=pd.Series([1.,2.,3.,2.])
        single=pd.DataFrame({"x":[4.],"z":[1.]})
        with_extreme=pd.concat([single,pd.DataFrame({"x":[1e12],"z":[1e12]})],ignore_index=True)
        a=ridge_predict(train,y,single)
        b=ridge_predict(train,y,with_extreme)
        self.assertAlmostEqual(a[0],b[0])

    def test_macro_features_have_sector_interactions(self):
        panel=synthetic_panel(periods=1)
        x=feature_frame(panel,"top_down")
        self.assertIn("td_topic_growth_tone_x_Industrials",x.columns)
        self.assertNotEqual(x.loc[0,"td_topic_growth_tone_x_Industrials"],x.loc[1,"td_topic_growth_tone_x_Industrials"])

    def test_ablation_removes_topic_from_both_sources_and_interactions(self):
        x=feature_frame(synthetic_panel(periods=2),"combined_without_inflation")
        self.assertFalse(any("topic_inflation_" in col for col in x.columns))
        self.assertNotIn("interaction_inflation",x.columns)
        self.assertIn("bu_tone",x.columns)
        self.assertIn("td_topic_employment_tone",x.columns)

    def test_missing_selected_return_does_not_renormalize_portfolio(self):
        rows=[]
        for i in range(12):
            rows.append({"model":"bottom_up","formation_date":"2024-03-28","ticker":f"T{i}","prediction":i,"stock_return":np.nan if i==11 else .1})
        result=portfolio_series(pd.DataFrame(rows))
        self.assertEqual(result.iloc[0].status,"missing_selected_returns")
        self.assertTrue(np.isnan(result.iloc[0].net_return))

    def test_initial_turnover_counts_both_long_and_short(self):
        rows=[{"model":"bottom_up","formation_date":"2024-03-28","ticker":f"T{i}","prediction":i,"stock_return":.01*i} for i in range(12)]
        result=portfolio_series(pd.DataFrame(rows),cost_bps=10.)
        self.assertAlmostEqual(result.iloc[0].turnover,2.)
        self.assertAlmostEqual(result.iloc[0]["cost"],.002)
        self.assertAlmostEqual(result.iloc[0].gross_return,.08)

    def test_insufficient_history_returns_empty_forecasts(self):
        predictions,folds=expanding_predictions(synthetic_panel(periods=4))
        self.assertTrue(predictions.empty)
        self.assertEqual(folds,[])

    def test_missing_topics_cannot_create_fake_ic(self):
        panel=synthetic_panel()
        panel["bu_topic_employment_tone"]=np.nan
        validity=signal_validity(panel)
        result=validity[(validity.scope=="All") & (validity.signal=="bu_topic_employment_tone")].iloc[0]
        self.assertEqual(result.n_periods,0)
        self.assertTrue(pd.isna(result.mean_ic))

    def test_disagreement_origin_scaling_is_not_refit_on_future(self):
        dates=pd.period_range("2016Q1",periods=20,freq="Q")
        series=pd.DataFrame({"scope":"All","topic":"overall","formation_date":[d.end_time.strftime("%Y-%m-%d") for d in dates],
                             "bottom_up":[float(i%3) for i in range(20)],"top_down":[float((i+1)%3) for i in range(20)],"n_firms":33})
        series.loc[12,"bottom_up"]=5.
        first,_=disagreement_analysis(series)
        revised=series.copy()
        revised.loc[revised.index>=15,["bottom_up","top_down"]]=999.
        second,_=disagreement_analysis(revised)
        a=first[first.formation_date.eq(series.loc[12,"formation_date"])].iloc[0]
        b=second[second.formation_date.eq(series.loc[12,"formation_date"])].iloc[0]
        self.assertAlmostEqual(a.gap,b.gap)
        self.assertAlmostEqual(a.next_gap_frozen_scale,b.next_gap_frozen_scale)


if __name__ == "__main__":
    unittest.main()
