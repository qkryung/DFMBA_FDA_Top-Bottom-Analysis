"""Identity, denominator, and calendar boundaries introduced by full coverage."""
import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from topbottom.analysis import build_panel,model_metrics,aggregate_text_series
from topbottom.coverage import coverage_funnel
from topbottom.market import prepare_market
from tests.test_analysis import document,synthetic_panel


class FullScopeTests(unittest.TestCase):
    def test_active_identity_ambiguity_fund_and_ticker_reuse_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            pd.DataFrame({"PERMNO":[1,1,2,3,4],"Ticker":["REUSED","NEW","DUAL","DUAL","FUND"],
                "MthCalDt":["2023-12-29","2024-12-31","2024-12-31","2024-12-31","2024-12-31"],
                "MthRet":[.01]*5,"MthPrc":[10]*5,"ShrOut":[100]*5,
                "SecurityNm":["Issuer1; COM NONE; CONS"]*2+["Issuer2; COM A; CONS","Issuer2; COM B; CONS","Unrelated fund"],
                "SecurityType":["EQTY"]*4+["FUND"]}).to_csv(p/"crsp.csv",index=False)
            (p/"ff.csv").write_text("202412,1,0,0,0\n",encoding="utf-8")
            first=prepare_market(p/"crsp.csv",p/"ff.csv",["REUSED","DUAL","FUND"],p/"out")
            self.assertEqual(first["n_tickers"],0)
            status=pd.read_csv(p/"out/market_mapping_audit.csv").set_index("ticker").mapping_status
            self.assertEqual(status["REUSED"],"historical_ticker_endpoint_differs")
            self.assertEqual(status["DUAL"],"ambiguous_active_ticker")
            self.assertEqual(status["FUND"],"non_equity_identity_conflict")
            alias={"DUAL":{"source_ticker":"DUAL","security_name":"Issuer2; COM A; CONS","reason":"Reviewed class A identity","source_url":"https://example.com/issuer"}}
            chosen=prepare_market(p/"crsp.csv",p/"ff.csv",["DUAL"],p/"chosen",aliases=alias)
            self.assertEqual(chosen["n_tickers"],1)
            self.assertTrue(prepare_market(p/"crsp.csv",p/"ff.csv",["DUAL"],p/"chosen",aliases=alias)["cache_reused"])

    def test_panel_excludes_pre_market_history_and_unmatched_issuer(self):
        firms=pd.DataFrame([document("a","2024-02-01T00:00:00Z",ticker="AAA"),document("b","2024-02-01T00:00:00Z",ticker="BBB"),document("c","2024-02-01T00:00:00Z",ticker="CCC")])
        fed=pd.DataFrame([document("fed","2024-01-01T00:00:00Z")])
        monthly=pd.DataFrame({"ticker":["AAA","AAA","BBB"],"month":["2024-03","2024-06","2024-06"],"date":["2024-03-28","2024-06-28","2024-06-28"],"return":[0,0,0]})
        factors=pd.DataFrame({"month":["2024-03","2024-06"],"market_return":[0,0]})
        panel,excluded=build_panel(firms,fed,monthly,factors)
        self.assertEqual(set(panel.ticker),{"AAA"})
        self.assertEqual(excluded["pre_available_market_history"],1)
        self.assertEqual(excluded["no_price_mapping"],2)

    def test_fixed_denominators_distinguish_pending_no_docs_and_unmatched(self):
        universe=pd.DataFrame({"ticker":["A","B","C","D"],"issuer_id":[1,2,3,4],"sector":["X"]*4})
        ledger=pd.DataFrame({"ticker":["A","B","C","D"],"status":["completed","completed","no_eligible_filings","pending"],"filing_regime":["8-K","8-K","6-K","unknown"],"error_category":[np.nan]*4})
        firms=pd.DataFrame({"ticker":["A","B"]})
        monthly=pd.DataFrame({"ticker":["A","C"]})
        panel=pd.DataFrame({"ticker":["A"]})
        pred=pd.DataFrame({"ticker":["A"],"excess_return":[.1]})
        coverage,sector,issuer=coverage_funnel(universe,ledger,firms,monthly,panel,pred,target_securities=5)
        self.assertEqual([coverage[k] for k in ("target_issuers","attempted_issuers","document_issuers","market_matched_issuers","analysis_issuers","oos_issuers")],[4,3,2,1,1,1])
        self.assertEqual(coverage["quarantined_issuers"],1)
        self.assertEqual(coverage["market_matched_issuers_all_target"],2)
        self.assertEqual(issuer.set_index("ticker").loc["C","exclusion_reason"],"no_eligible_filings")
        self.assertEqual(issuer.set_index("ticker").loc["C","filing_regime"],"6-K")

    def test_interior_portfolio_gap_never_compacts_into_annualized_result(self):
        pred=pd.DataFrame({"model":["combined"]*3,"formation_date":["2020-03-31","2020-06-30","2020-09-30"],"prediction":[.1,.2,.3],"excess_return":[.1,.2,.3]})
        ports=pd.DataFrame({"model":["combined"]*3,"formation_date":pred.formation_date,"status":["observed","missing_selected_returns","observed"],"net_return":[.1,np.nan,.1]})
        row=model_metrics(pred,ports).iloc[0]
        self.assertIsNone(row.annualized_return)
        self.assertIsNone(row.max_drawdown)
        self.assertEqual(row.portfolio_calendar_status,"incomplete_or_different_calendar")

    def test_text_membership_change_is_reported_separately_from_mean_change(self):
        panel=synthetic_panel(2,3)
        panel=panel[~((panel.ticker=="T2") & (panel.formation_date==panel.formation_date.max()))]
        series=aggregate_text_series(panel)
        overall=series[(series.scope=="All") & (series.topic=="overall")]
        self.assertAlmostEqual(overall.iloc[-1].membership_change_fraction,1/3)


if __name__=="__main__":
    unittest.main()
