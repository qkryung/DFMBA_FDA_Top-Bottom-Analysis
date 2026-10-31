"""Point-in-time quarterly text/return research, using pandas + NumPy only.

All return values are decimal returns. LM tone is percentage points of words.
Research results are exploratory associations, not causal or trading claims.
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TOPICS = ("inflation", "employment", "growth", "investment", "rates")
SECTORS = ("Communication Services", "Consumer Discretionary", "Consumer Staples",
           "Energy", "Financials", "Health Care", "Industrials", "Information Technology",
           "Materials", "Real Estate", "Utilities")


def ticker_key(value: Any) -> str:
    return str(value).upper().strip().replace("-", ".")


def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def require_unique(frame: pd.DataFrame, keys: list[str], label: str) -> None:
    if frame.duplicated(keys).any():
        raise ValueError(f"{label}: duplicate keys {keys}: {int(frame.duplicated(keys).sum())}")


def normalize_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep a missing topic missing; a score of zero needs an observed sentence."""
    out = frame.copy()
    if out.empty:
        return out
    out["published_at"] = pd.to_datetime(out["published_at"], utc=True, format="ISO8601", errors="raise")
    if "ticker" in out:
        out["ticker"] = out["ticker"].map(ticker_key)
    if "uncertainty_rate" not in out:
        out["uncertainty_rate"] = pd.to_numeric(out["uncertainty"], errors="coerce") / pd.to_numeric(out["word_count"], errors="coerce") * 100
    for topic in TOPICS:
        score, share = f"topic_{topic}_tone", f"topic_{topic}_share"
        if score not in out:
            out[score] = np.nan
        if share in out:
            out.loc[pd.to_numeric(out[share], errors="coerce").fillna(0).eq(0), score] = np.nan
    if "forward_tone" not in out:
        out["forward_tone"] = np.nan
    if "forward_sentence_count" in out:
        out.loc[out["forward_sentence_count"].fillna(0).eq(0), "forward_tone"] = np.nan
    require_unique(out, ["ticker", "doc_id"] if "ticker" in out else ["doc_id"], "scores")
    return out.sort_values(["published_at", "doc_id"]).reset_index(drop=True)


from .market import prepare_market


def compound_exact(monthly: pd.DataFrame, months: list[str], column: str) -> float:
    """Compound only a full exact calendar window; missing is never zero."""
    if monthly.empty or monthly.month.duplicated().any():
        return float("nan")
    subset = monthly.set_index("month").reindex(months)[column]
    if subset.isna().any() or len(subset) != len(months):
        return float("nan")
    return float(np.prod(1 + subset.to_numpy(dtype=float)) - 1)


def build_panel(firms: pd.DataFrame, fomc: pd.DataFrame, monthly: pd.DataFrame, factors: pd.DataFrame,
                max_age_days: int = 120, horizon: int = 3) -> tuple[pd.DataFrame, dict]:
    """Quarter-end signals and next three complete calendar-month returns.

    Availability cutoff is 00:00 UTC on the last CRSP trading date, strictly
    before the entry closing price. This deliberately drops same-day releases.
    """
    firms, fomc = normalize_scores(firms), normalize_scores(fomc)
    market = monthly.copy()
    market["ticker"] = market.ticker.map(ticker_key)
    market["date"] = pd.to_datetime(market.date)
    if "month" not in market:
        market["month"] = market.date.dt.to_period("M").astype(str)
    require_unique(market, ["ticker", "month"], "monthly returns")
    require_unique(factors, ["month"], "market factors")
    scorecols = ["tone", "uncertainty_rate", "forward_tone"] + [f"topic_{x}_tone" for x in TOPICS]
    dates = market.groupby("month").date.max().sort_values()
    dates = dates[dates.dt.month.isin([3, 6, 9, 12])]
    rows, excluded = [], {"no_firm_history_or_stale": 0, "no_fomc_history": 0, "outcome_incomplete": 0,
                          "no_price_mapping":0,"pre_available_market_history":0,"post_available_market_history":0,"missing_entry_month":0}
    firms_by_ticker = dict(tuple(firms.groupby("ticker")))
    market_by_ticker = dict(tuple(market.groupby("ticker")))
    firm_times={t:g.published_at.dt.tz_convert(None).to_numpy(dtype="datetime64[ns]") for t,g in firms_by_ticker.items()}
    macro_times=fomc.published_at.dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")
    returns_lookup=dict(zip(zip(market.ticker,market.month),market["return"]))
    market_months={t:set(g.month) for t,g in market_by_ticker.items()}
    market_ranges={t:(g.month.min(),g.month.max()) for t,g in market_by_ticker.items()}
    benchmark_lookup=dict(zip(factors.month,factors.market_return))
    def from_values(values):
        return float(np.prod(1+np.asarray(values,dtype=float))-1) if np.isfinite(values).all() else np.nan
    for dt in dates:
        cutoff = pd.Timestamp(dt.date(), tz="UTC")
        if cutoff < firms.published_at.min():
            continue
        period = pd.Period(dt, freq="M")
        future = [str(period + x) for x in range(1, horizon+1)]
        # Entry-month close is still unknown at the midnight cutoff. Momentum
        # therefore uses the three months ending one full month before entry.
        prior = [str(period-x) for x in reversed(range(1,horizon+1))]
        cutoff_np=np.datetime64(cutoff.tz_localize(None),"ns")
        macro_idx=int(np.searchsorted(macro_times,cutoff_np,side="left"))-1
        if macro_idx<0:
            excluded["no_fomc_history"] += len(firms_by_ticker)
            continue
        macro = fomc.iloc[macro_idx]
        mret=from_values([benchmark_lookup.get(m,np.nan) for m in future])
        formation_month=str(period)
        for ticker, history in firms_by_ticker.items():
            if ticker not in market_months:
                excluded["no_price_mapping"]+=1
                continue
            first_market,last_market=market_ranges[ticker]
            if formation_month<first_market:
                excluded["pre_available_market_history"]+=1
                continue
            if formation_month>last_market:
                excluded["post_available_market_history"]+=1
                continue
            if formation_month not in market_months[ticker]:
                excluded["missing_entry_month"]+=1
                continue
            firm_idx=int(np.searchsorted(firm_times[ticker],cutoff_np,side="left"))-1
            if firm_idx<0:
                excluded["no_firm_history_or_stale"] += 1
                continue
            firm = history.iloc[firm_idx]
            if firm.published_at<cutoff-pd.Timedelta(days=max_age_days):
                excluded["no_firm_history_or_stale"]+=1
                continue
            ret=from_values([returns_lookup.get((ticker,m),np.nan) for m in future])
            momentum=from_values([returns_lookup.get((ticker,m),np.nan) for m in prior])
            complete = bool(np.isfinite(ret) and np.isfinite(mret))
            excluded["outcome_incomplete"] += int(not complete)
            row = {"ticker": ticker, "sector": firm.sector, "formation_date": dt.strftime("%Y-%m-%d"), "cutoff": cutoff.isoformat(), "label_end": (period+horizon).end_time.strftime("%Y-%m-%d"), "firm_doc_id": firm.doc_id, "firm_published_at": firm.published_at.isoformat(), "fomc_doc_id": macro.doc_id, "fomc_published_at": macro.published_at.isoformat(), "firm_age_days": (cutoff-firm.published_at).days, "stock_return": ret, "market_return": mret, "excess_return": ret-mret if complete else np.nan, "momentum": momentum, "outcome_complete": complete}
            for c in scorecols:
                row[f"bu_{c}"] = firm.get(c, np.nan)
                row[f"td_{c}"] = macro.get(c, np.nan)
            rows.append(row)
    panel = pd.DataFrame(rows)
    if not panel.empty:
        require_unique(panel, ["ticker", "formation_date"], "panel")
    return panel, excluded


def rank_corr(x: pd.Series, y: pd.Series, min_n: int = 3) -> float:
    z = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(z) < min_n or z.x.nunique() < 2 or z.y.nunique() < 2:
        return float("nan")
    return float(z.x.rank().corr(z.y.rank()))


def hac_mean(values: list[float] | pd.Series, lag: int = 1) -> dict:
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    if not len(a):
        return {"n": 0, "mean": None, "hac_se": None, "hac_t": None}
    mean = float(a.mean())
    if len(a) < 8:
        return {"n": len(a), "mean": mean, "hac_se": None, "hac_t": None}
    e = a-mean
    longvar = float(e@e/len(e))
    for j in range(1, min(lag, len(a)-1)+1):
        longvar += 2*(1-j/(lag+1))*float(e[j:]@e[:-j]/len(e))
    se = float(np.sqrt(max(longvar, 0)/len(e)))
    return {"n": len(a), "mean": mean, "hac_se": se, "hac_t": mean/se if se>1e-12 else None}


def signal_validity(panel: pd.DataFrame) -> pd.DataFrame:
    """Equal-period average cross-sectional rank IC, with HAC over periods."""
    if panel.empty:
        return pd.DataFrame()
    signals = ["bu_tone", "bu_uncertainty_rate", "bu_forward_tone"]+[f"bu_topic_{x}_tone" for x in TOPICS]
    rows = []
    scopes = [("All", panel)] + list(panel.groupby("sector"))
    for scope, group in scopes:
        for signal in signals:
            ics, counts = [], []
            for _, period in group.groupby("formation_date"):
                valid = period[[signal, "excess_return"]].dropna()
                ic = rank_corr(valid[signal], valid.excess_return, min_n=5 if scope=="All" else 3)
                if np.isfinite(ic):
                    ics.append(ic)
                    counts.append(len(valid))
            estimate = hac_mean(ics)
            rows.append({"scope": scope, "signal": signal, "n_periods": estimate["n"], "mean_ic": estimate["mean"], "hac_t": estimate["hac_t"], "median_firms_per_period": float(np.median(counts)) if counts else None, "status": "exploratory" if len(ics)>=8 else "insufficient", "note": "Contemporaneous formation score vs next 3-month market-adjusted return; multiple testing, no causal interpretation."})
    return pd.DataFrame(rows)


def feature_frame(panel: pd.DataFrame, model: str) -> pd.DataFrame:
    ablated = model.removeprefix("combined_without_") if model.startswith("combined_without_") else None
    if ablated is not None:
        if ablated not in TOPICS:
            raise ValueError(f"Unknown topic ablation: {ablated}")
        model = "combined"
    x = {}
    x["momentum"] = panel.momentum
    for sector in SECTORS[1:]:
        x[f"sector_{sector}"] = panel.sector.eq(sector).astype(float)
    bu = ["bu_tone", "bu_uncertainty_rate", "bu_forward_tone"]+[f"bu_topic_{t}_tone" for t in TOPICS]
    td = ["td_tone", "td_uncertainty_rate"]+[f"td_topic_{t}_tone" for t in TOPICS]
    if model in ("bottom_up", "combined"):
        for col in bu:
            x[col] = pd.to_numeric(panel[col], errors="coerce")
    if model in ("top_down", "combined"):
        for col in td:
            x[col] = pd.to_numeric(panel[col], errors="coerce")
            for sector in SECTORS[1:]:
                x[f"{col}_x_{sector}"] = x[col]*panel.sector.eq(sector).astype(float)
    if model == "combined":
        x["bu_x_td"] = panel.bu_tone * panel.td_tone
        for t in TOPICS:
            x[f"interaction_{t}"] = panel[f"bu_topic_{t}_tone"] * panel[f"td_topic_{t}_tone"]
    if ablated:
        x = {name:value for name,value in x.items() if f"topic_{ablated}_" not in name and name != f"interaction_{ablated}"}
    return pd.DataFrame(x, index=panel.index)


def ridge_predict(train_x: pd.DataFrame, train_y: pd.Series, test_x: pd.DataFrame,
                  alpha: float = 10.0) -> np.ndarray:
    """Training-only imputation, missingness flags, standardization, ridge fit."""
    a, b = train_x.to_numpy(float), test_x.to_numpy(float)
    medians = np.array([np.nanmedian(a[:, i]) if np.isfinite(a[:, i]).any() else 0. for i in range(a.shape[1])])
    a_missing, b_missing = ~np.isfinite(a), ~np.isfinite(b)
    a = np.concatenate([np.where(a_missing, medians, a), a_missing.astype(float)], axis=1)
    b = np.concatenate([np.where(b_missing, medians, b), b_missing.astype(float)], axis=1)
    mu, sd = a.mean(axis=0), a.std(axis=0)
    varying = sd>=1e-10
    a, b, mu, sd = a[:,varying], b[:,varying], mu[varying], sd[varying]
    a, b = (a-mu)/sd, (b-mu)/sd
    y = train_y.to_numpy(float)
    coeff = np.linalg.solve(a.T@a + alpha*np.eye(a.shape[1]), a.T@(y-y.mean()))
    return y.mean()+b@coeff


def expanding_predictions(panel: pd.DataFrame, min_train_periods: int = 12,
                          min_train_rows: int = 100, alpha: float = 10., include_ablation: bool = False) -> tuple[pd.DataFrame, list[dict]]:
    if panel.empty:
        return pd.DataFrame(), []
    results, folds = [], []
    models = ("baseline", "bottom_up", "top_down", "combined")
    if include_ablation:
        models += tuple(f"combined_without_{t}" for t in TOPICS)
    features = {m: feature_frame(panel, m) for m in models}
    for dt, test in panel.groupby("formation_date"):
        # Date strictly earlier: an outcome ending on formation day isn't available
        # at the midnight signal cutoff and is not included in training.
        train = panel[(panel.label_end < dt) & panel.excess_return.notna()]
        nperiods = int(train.formation_date.nunique())
        if nperiods < min_train_periods or len(train) < min_train_rows:
            continue
        folds.append({"test_date": dt, "train_periods": nperiods, "train_rows": len(train), "test_rows": len(test), "latest_label_end": train.label_end.max()})
        for model in models:
            pred = ridge_predict(features[model].loc[train.index], train.excess_return, features[model].loc[test.index], alpha)
            out = test[["ticker", "sector", "formation_date", "label_end", "stock_return", "market_return", "excess_return"]].copy()
            out["model"], out["prediction"] = model, pred
            results.append(out)
    return (pd.concat(results, ignore_index=True) if results else pd.DataFrame()), folds


def portfolio_series(predictions: pd.DataFrame, cost_bps: float = 10.) -> pd.DataFrame:
    """100% long, 100% short terciles; explicit drift-adjusted dollar turnover.

    A period with missing selected-name returns is not silently reweighted. Short
    borrow/funding and market impact are not modeled; 10bp is a scenario.
    """
    if predictions.empty:
        return pd.DataFrame()
    rows = []
    for model, pred in predictions.groupby("model"):
        previous: dict[str, float] = {}
        for date, group in pred.groupby("formation_date"):
            if len(group)<9 or group.prediction.nunique()<3:
                continue
            low, high = group.prediction.quantile([1/3, 2/3])
            longs, shorts = group[group.prediction>high], group[group.prediction<low]
            if longs.empty or shorts.empty:
                continue
            weights = {**dict.fromkeys(longs.ticker, 1/len(longs)), **dict.fromkeys(shorts.ticker, -1/len(shorts))}
            selected = group.set_index("ticker").loc[list(weights)]
            if selected.stock_return.isna().any():
                rows.append({"model": model, "formation_date": date, "status": "missing_selected_returns", "gross_return": np.nan, "net_return": np.nan})
                previous = {}
                continue
            turnover = sum(abs(weights.get(t, 0)-previous.get(t, 0)) for t in set(weights)|set(previous))
            gross = float(sum(w*selected.loc[t, "stock_return"] for t,w in weights.items()))
            costs = turnover*cost_bps/10000
            rows.append({"model": model, "formation_date": date, "status": "observed", "n_long": len(longs), "n_short": len(shorts), "gross_return": gross, "turnover": turnover, "cost": costs, "net_return": gross-costs})
            previous = {t: w*(1+float(selected.loc[t, "stock_return"]))/max(1+gross-costs, 1e-9) for t,w in weights.items()}
    return pd.DataFrame(rows)


def model_metrics(predictions: pd.DataFrame, portfolios: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame()
    rows = []
    observed_sets={m:set(g.loc[g.status.eq("observed"),"formation_date"]) for m,g in portfolios.groupby("model")} if len(portfolios) else {}
    common_portfolio_calendar=len({frozenset(v) for v in observed_sets.values()})<=1
    for model, group in predictions.groupby("model"):
        complete = group.dropna(subset=["excess_return"])
        ics = [rank_corr(g.prediction, g.excess_return, 5) for _,g in complete.groupby("formation_date")]
        ic = hac_mean(ics)
        port = portfolios[(portfolios.model==model) & portfolios.status.eq("observed")] if not portfolios.empty else pd.DataFrame()
        net = port.net_return if len(port) else pd.Series(dtype=float)
        ordinals=sorted(pd.Period(d,freq="Q").ordinal for d in port.formation_date) if len(port) else []
        continuous=bool(ordinals) and all(b-a==1 for a,b in zip(ordinals,ordinals[1:]))
        comparable_calendar=continuous and common_portfolio_calendar
        nm = hac_mean(net)
        annual_vol = float(net.std(ddof=1)*2) if len(net)>1 and comparable_calendar else None
        annual_return = float(np.prod(1+net)**(4/len(net))-1) if len(net) and (1+net).gt(0).all() and comparable_calendar else None
        wealth = np.r_[1., np.cumprod(1+net.to_numpy())] if len(net) else np.array([1.])
        rows.append({"model": model, "n_oos": len(complete), "n_periods": int(complete.formation_date.nunique()), "mean_ic": ic["mean"], "ic_hac_t": ic["hac_t"], "rmse": float(np.sqrt(np.mean((complete.prediction-complete.excess_return)**2))) if len(complete) else None, "net_quarterly_mean": nm["mean"], "net_hac_t": nm["hac_t"] if comparable_calendar else None, "annualized_return": annual_return, "annualized_volatility": annual_vol, "sharpe_zero_rate": float(net.mean()/net.std(ddof=1)*2) if len(net)>1 and net.std(ddof=1)>0 and comparable_calendar else None, "max_drawdown": float(np.min(wealth/np.maximum.accumulate(wealth)-1)) if len(net) and comparable_calendar else None, "n_portfolio_periods": len(net), "portfolio_calendar_status":"common_contiguous" if comparable_calendar else "incomplete_or_different_calendar", "cost_bps": 10., "status": "exploratory" if ic["n"]>=8 else "insufficient"})
    return pd.DataFrame(rows)


def sector_model_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    """Evaluate the same pooled model within each sector; no separate refitting."""
    if predictions.empty:
        return pd.DataFrame()
    rows = []
    for (sector, model), group in predictions.groupby(["sector", "model"]):
        complete = group.dropna(subset=["excess_return"])
        ics = [rank_corr(g.prediction,g.excess_return,3) for _,g in complete.groupby("formation_date")]
        ic = hac_mean(ics)
        means = complete.groupby("formation_date")[["prediction","excess_return"]].mean()
        rows.append({"sector": sector, "model": model, "n_oos": len(complete), "n_periods": len(means),
                     "mean_ic": ic["mean"], "ic_hac_t": ic["hac_t"],
                     "rmse": float(np.sqrt(np.mean((complete.prediction-complete.excess_return)**2))) if len(complete) else None,
                     "sector_mean_time_series_rank_corr": rank_corr(means.prediction,means.excess_return,8) if len(means)>=8 else None,
                     "median_firms_per_period": float(complete.groupby("formation_date").size().median()) if len(complete) else None,
                     "status": "exploratory_small_sector" if len(complete) and complete.groupby("formation_date").size().median()<10 else "exploratory"})
    return pd.DataFrame(rows)


def topic_ablation_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    """Incremental value of topic-specific features, holding OOS folds fixed.

    Overall tone still contains all words. Thus this removes explicit topic
    features, not every trace of that economic subject from the text.
    """
    if predictions.empty:
        return pd.DataFrame()
    rows=[]
    scopes=[("All",predictions)]+list(predictions.groupby("sector"))
    for scope,sample in scopes:
        full=sample[sample.model.eq("combined")][["ticker","formation_date","prediction","excess_return"]].rename(columns={"prediction":"full_prediction"})
        for topic in TOPICS:
            ablated=sample[sample.model.eq(f"combined_without_{topic}")][["ticker","formation_date","prediction"]].rename(columns={"prediction":"without_prediction"})
            paired=full.merge(ablated,on=["ticker","formation_date"],validate="one_to_one").dropna()
            if paired.empty:
                continue
            full_rmse=float(np.sqrt(np.mean((paired.full_prediction-paired.excess_return)**2)))
            without_rmse=float(np.sqrt(np.mean((paired.without_prediction-paired.excess_return)**2)))
            min_firms=5 if scope=="All" else 3
            full_ic=hac_mean([rank_corr(g.full_prediction,g.excess_return,min_firms) for _,g in paired.groupby("formation_date")])["mean"]
            without_ic=hac_mean([rank_corr(g.without_prediction,g.excess_return,min_firms) for _,g in paired.groupby("formation_date")])["mean"]
            rows.append({"scope":scope,"topic":topic,"n_oos":len(paired),"n_periods":int(paired.formation_date.nunique()),
                         "full_rmse":full_rmse,"without_rmse":without_rmse,"rmse_increase":without_rmse-full_rmse,
                         "rmse_increase_pct":(without_rmse/full_rmse-1)*100 if full_rmse else None,
                         "full_mean_ic":full_ic,"without_mean_ic":without_ic,"ic_loss":full_ic-without_ic if full_ic is not None and without_ic is not None else None,
                         "status":"exploratory_ablation","note":"Same training/test folds; explicit topic features removed from BU, TD and interactions. General document tone remains; not causal topic influence."})
    return pd.DataFrame(rows)


def aggregate_text_series(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    rows = []
    for scope, sample in [("All", panel)] + list(panel.groupby("sector")):
        previous_members={}
        for date, g in sample.groupby("formation_date"):
            for topic in ("overall",)+TOPICS:
                suffix = "tone" if topic=="overall" else f"topic_{topic}_tone"
                members=set(g.loc[g[f"bu_{suffix}"].notna(),"ticker"])
                old=previous_members.get(topic)
                union=members|old if old is not None else set()
                change=len(members.symmetric_difference(old))/len(union) if old is not None and union else None
                rows.append({"scope": scope, "formation_date": date, "topic": topic, "bottom_up": g[f"bu_{suffix}"].mean(), "top_down": g[f"td_{suffix}"].iloc[0], "n_firms": len(members),"membership_change_fraction":change})
                previous_members[topic]=members
    return pd.DataFrame(rows)


def disagreement_analysis(series: pd.DataFrame, min_history: int = 12, gap_threshold: float = 1.) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Frozen origin scaling for retrospective convergence; OOS cross-signal AR.

    Relative tone is not an economic/hawkish direction label. Outcomes here are
    recorded only for diagnosis; never become contemporaneous trading features.
    """
    if series.empty:
        return pd.DataFrame(), pd.DataFrame()
    resolutions, leads = [], []
    for (scope, topic), g in series.groupby(["scope", "topic"]):
        g = g.sort_values("formation_date").reset_index(drop=True)
        for i in range(min_history, len(g)-1):
            hist = g.iloc[:i].dropna(subset=["bottom_up", "top_down"])
            if len(hist)<min_history:
                continue
            now, nxt = g.iloc[i], g.iloc[i+1]
            if pd.Period(nxt.formation_date,freq="Q") != pd.Period(now.formation_date,freq="Q")+1:
                continue
            if not np.isfinite([now.bottom_up, now.top_down, nxt.bottom_up, nxt.top_down]).all():
                continue
            means = hist[["bottom_up", "top_down"]].mean()
            sds = hist[["bottom_up", "top_down"]].std(ddof=0)
            if (sds<1e-10).any():
                continue
            b, m = (now.bottom_up-means.bottom_up)/sds.bottom_up, (now.top_down-means.top_down)/sds.top_down
            bn, mn = (nxt.bottom_up-means.bottom_up)/sds.bottom_up, (nxt.top_down-means.top_down)/sds.top_down
            gap, nextgap = b-m, bn-mn
            if abs(gap)<gap_threshold:
                continue
            corporate, fed = -np.sign(gap)*(bn-b), np.sign(gap)*(mn-m)
            if abs(nextgap)>abs(gap)*.75:
                outcome = "persistent_or_diverging"
            elif corporate>0 and fed>0:
                outcome = "both_adjust"
            elif corporate>fed:
                outcome = "corporate_toward_fed"
            else:
                outcome = "fed_toward_corporate"
            resolutions.append({"scope": scope, "topic": topic, "formation_date": now.formation_date, "next_date": nxt.formation_date, "gap": gap, "next_gap_frozen_scale": nextgap, "outcome": outcome, "corporate_contribution": corporate, "fed_contribution": fed})
        # AR(1) vs AR(1)+other-source signal, expanding train. All pairs end before
        # the current forecast origin; completed text outcomes only, no returns.
        for target, other, direction in [("top_down", "bottom_up", "bottom_up_to_top_down"), ("bottom_up", "top_down", "top_down_to_bottom_up")]:
            pairs = g[["formation_date", target, other]].copy()
            pairs["target_next"] = pairs[target].shift(-1)
            quarter_ordinals = pd.to_datetime(pairs.formation_date).dt.to_period("Q").map(lambda p:p.ordinal)
            pairs.loc[quarter_ordinals.shift(-1)-quarter_ordinals != 1,"target_next"] = np.nan
            errors = []
            for i in range(min_history, len(pairs)-1):
                train = pairs.iloc[:i].dropna()
                test = pairs.iloc[[i]].dropna()
                if len(train)<min_history or test.empty:
                    continue
                base = ridge_predict(train[[target]], train.target_next, test[[target]], alpha=1.)[0]
                cross = ridge_predict(train[[target,other]], train.target_next, test[[target,other]], alpha=1.)[0]
                errors.append((float(test.target_next.iloc[0])-base, float(test.target_next.iloc[0])-cross))
            if errors:
                err = np.asarray(errors)
                rb, rc = np.sqrt((err**2).mean(axis=0))
                leads.append({"scope": scope, "topic": topic, "direction": direction, "n_oos": len(errors), "rmse_own_lag": float(rb), "rmse_with_other": float(rc), "improvement_pct": float((1-rc/rb)*100) if rb>0 else None, "status": "exploratory" if len(errors)>=8 else "insufficient"})
    return pd.DataFrame(resolutions), pd.DataFrame(leads)


def descriptive_report(firms: pd.DataFrame, fomc: pd.DataFrame) -> dict:
    sector = firms.groupby("sector").agg(documents=("doc_id", "size"), firms=("ticker", "nunique"), mean_tone=("tone", "mean")).reset_index()
    timeline = []
    for name, data in [("firm",firms),("fomc",fomc)]:
        years = pd.to_datetime(data.published_at, utc=True, format="ISO8601").dt.year.value_counts().sort_index()
        timeline += [{"source": name, "year": int(y), "documents": int(n)} for y,n in years.items()]
    topics = []
    for name, data in [("firm",firms),("fomc",fomc)]:
        for topic in TOPICS:
            share = f"topic_{topic}_share"
            tone = f"topic_{topic}_tone"
            topics.append({"source": name, "topic": topic, "mean_share": float(data[share].mean()) if share in data else None, "mean_tone": float(data[tone].mean()) if data[tone].notna().any() else None, "n_documents_with_topic": int(data[tone].notna().sum())})
    return {"sector_coverage": records(sector), "document_timeline": timeline, "fomc_topics": topics, "score_summary": [{"source": name, "mean_tone": float(data.tone.mean()), "median_words": float(data.word_count.median())} for name,data in [("firm",firms),("fomc",fomc)]]}


def derive_findings(coverage: dict, metrics: pd.DataFrame, leads: pd.DataFrame) -> list[dict]:
    """Narrative derived from saved metrics; no performance-driven model tuning."""
    labels={"baseline":"기본 통제변수", "bottom_up":"바텀업", "top_down":"탑다운", "combined":"결합"}
    full=coverage.get("target_issuers",0)>33
    title="현재 구성 발행사 전수 수집과 실제 분석 범위" if full else "실제 자료로 실행한 탐색적 파일럿"
    scope_text=(f"목표 {coverage['target_issuers']}개 발행사 중 {coverage['attempted_issuers']}개 수집 시도, {coverage['document_issuers']}개 문서 확보, {coverage['analysis_issuers']}개 분기 패널 연결, {coverage['oos_issuers']}개 완결 수익률 표본외 평가입니다. " if full else "")
    findings=[{"severity":"scope","title":title,
               "text":scope_text+f"2016–2025년에 공개된 기업 문서 {coverage['firm_documents']:,}건과 FOMC {coverage['fomc_documents']}건을 처리했습니다. 현재 구성종목을 과거에 적용한 표본이므로 역사적 S&P 500 전체의 결과는 아닙니다."}]
    if len(metrics) and len(metrics.dropna(subset=["rmse"])):
        comparable=metrics.dropna(subset=["rmse"])
        best=comparable.loc[comparable.rmse.idxmin()]
        text=f"{int(best.n_periods)}개 평가 분기에서 OOS RMSE가 가장 낮은 것은 {labels.get(best.model,best.model)} 모델({best.rmse:.4f})입니다."
        by_model=metrics.set_index("model")
        if {"combined","bottom_up","top_down"}.issubset(by_model.index):
            combined,bu,td=(by_model.loc[m] for m in ("combined","bottom_up","top_down"))
            text+=f" 결합 모델 RMSE는 {combined.rmse:.4f}이며, 평균 순위 IC는 결합 {combined.mean_ic:.4f}, 탑다운 {td.mean_ic:.4f}, 바텀업 {bu.mean_ic:.4f}입니다."
        text+=" 수익률 수준의 오차와 종목 순위는 다른 평가 기준입니다. 제한된 분기 표본의 탐색 결과로 모형 우월성이 확증된 것은 아닙니다."
        findings.append({"severity":"exploratory","title":"수익률 오차와 종목 순위 예측력을 함께 평가한다","text":text})
    else:
        findings.append({"severity":"missing","title":"OOS 결과 미산출","text":"최소 12개 성숙 분기·100개 학습 행 조건이 충족되지 않아 투자 성과를 만들어 내지 않았습니다."})
    if len(leads):
        overall=leads[leads.scope.eq("All") & leads.topic.eq("overall")].set_index("direction")
        if {"top_down_to_bottom_up","bottom_up_to_top_down"}.issubset(overall.index):
            td_to_bu,bu_to_td=(overall.loc[k] for k in ("top_down_to_bottom_up","bottom_up_to_top_down"))
            def change(value):
                return f"{abs(value):.2f}% {'감소' if value>=0 else '증가'}"
            text=f"전체 어조의 다음 분기 예측에서 자기 전기 값만 사용한 모형보다, 탑다운 정보를 추가한 바텀업 어조 RMSE는 {change(td_to_bu.improvement_pct)}, 바텀업 정보를 추가한 탑다운 어조 RMSE는 {change(bu_to_td.improvement_pct)}했습니다({int(td_to_bu.n_oos)}개 OOS 시점). 탐색적 차이이며 경제·실적 예측의 정확성이나 정보원의 우월성을 확증하지 않습니다."
            findings.append({"severity":"exploratory","title":"다른 정보원이 어조 예측에 추가하는 정보","text":text})
    return findings


def build_report(firms: pd.DataFrame, fomc: pd.DataFrame, panel: pd.DataFrame, exclusions: dict,
                 validity: pd.DataFrame, predictions: pd.DataFrame, portfolios: pd.DataFrame,
                 metrics: pd.DataFrame, series: pd.DataFrame, resolutions: pd.DataFrame,
                 leads: pd.DataFrame, folds: list[dict], market_meta: dict | None = None,
                 scope: str = "pilot", coverage_extra: dict | None = None) -> dict:
    firms, fomc = normalize_scores(firms), normalize_scores(fomc)
    evaluated = predictions.dropna(subset=["excess_return"]) if len(predictions) else predictions
    matched_panel = panel.dropna(subset=["excess_return"]) if len(panel) else panel
    coverage = {"firm_documents": len(firms), "fomc_documents": len(fomc), "tickers": int(firms.ticker.nunique()), "sectors": int(firms.sector.nunique()), "formation_periods": int(panel.formation_date.nunique()) if len(panel) else 0, "panel_rows": len(panel), "return_matched": int(panel.excess_return.notna().sum()) if len(panel) else 0, "excluded": exclusions, "first_firm_release": firms.published_at.min().isoformat(), "last_firm_release": firms.published_at.max().isoformat(), "oos_periods": int(evaluated.formation_date.nunique()) if len(evaluated) else 0, "forecast_periods": int(predictions.formation_date.nunique()) if len(predictions) else 0}
    coverage.update(firm_documents_used=int(panel.firm_doc_id.nunique()) if len(panel) else 0,
                    fomc_documents_used=int(panel.fomc_doc_id.nunique()) if len(panel) else 0,
                    first_fomc_release=fomc.published_at.min().isoformat(),
                    last_fomc_release=fomc.published_at.max().isoformat())
    coverage.update(coverage_extra or {})
    resolution_counts = records(resolutions.groupby(["scope","topic","outcome"]).size().reset_index(name="count")) if len(resolutions) else []
    limitations = [
        "The fixed current S&P 500 issuer universe is not historical index membership. Survivorship, corporate reorganizations, and unavailable sources limit generalization.",
        "Current GICS sector labels are held fixed; historical reclassifications and constituent membership are not reconstructed.",
        "A fixed course dictionary archive (20200204) is applied retrospectively across 2016-2025. Source and return availability are point-in-time, but the dictionary/model versions available at each historical date are not reconstructed; sampled FinBERT comparisons use one fixed revision.",
        "LM dictionary affect scores do not identify hawkishness, cost versus demand channels, or the economic direction of inflation/employment. Topic scores are common-topic tone proxies.",
        "SEC sources use acceptance as conservative availability. Verified official-IR replacements use the later of SEC acceptance and 00:00 America/New_York on the day after the stated IR release date; original timestamps remain recorded. Quarter-end inputs discard releases on the final trading day.",
        "Only disclosures no more than 120 days old enter formation; source collection failures can create nonrandom exclusions.",
        "OOS estimates have limited quarterly observations. HAC t-statistics do not correct dozens of topic/sector comparisons; all findings are exploratory.",
        "FOMC information is common across firms in each quarter; the macro time-series sample is the number of quarters, not the number of company-quarter rows.",
        "Topic means include only market-matched firms that mention the topic. Counts and membership change over time; mean changes are not exclusively within-firm perception changes.",
        "Market-adjusted BHAR equals stock buy-and-hold return minus broad US market buy-and-hold return; it is not factor alpha or an S&P 500-only benchmark.",
        "Long-short returns assume 100% long and 100% short exposure, quarterly close execution and 10 bp per dollar traded. Borrow fees, funding, slippage and market impact are unmodeled.",
        "The full-corpus FinBERT return backtest, EPS-surprise controls, accounting-outcome validation and causal identification are not part of the executed LM analysis. A separate sampled LM/FinBERT agreement experiment does not establish return predictive superiority.",
        "Text lead-lag and convergence describe source language. They do not establish which institution is correct about the economy or guarantee return predictability.",
        "Within a sector and quarter, TD features and TD-sector interactions are constant; within-sector TD stock rankings are driven by the varying momentum control. Sector-mean time-series performance is a different comparison.",
        "Ridge uses X'X + 10I. The fixed numerical penalty is unchanged from the pilot, but relative regularization weakens as training rows increase; pilot/full differences are not a pure sample-size experiment.",
        "The full run includes source-quality corrections discovered during the expanded audit, including previously retained pilot documents. The preserved pilot is an overlapping baseline, not an independent holdout; changes combine coverage, composition, source corrections and relative regularization.",
        "Annualized portfolio metrics and portfolio HAC are withheld if observed quarters have interior gaps or differ across models; missing selected returns are never silently reweighted.",
    ]
    modules = [
        {"id": "bottom_up_validity", "status": "executed_exploratory" if len(validity) else "unavailable", "question": "기업 어조는 향후 시장 대비 수익률과 관련되는가?", "method": "Quarterly cross-sectional Spearman IC, whole sample and GICS sectors; HAC over quarters."},
        {"id": "forecast_comparison", "status": "executed_exploratory" if len(predictions) else "unavailable_insufficient_history", "question": "바텀업·탑다운·결합 정보 중 무엇이 추가 예측력을 제공하는가?", "method": "Same-sample expanding OOS ridge; baseline controls, BU, TD with sector interactions, combined; minimum 12 matured training quarters."},
        {"id": "topic_sector", "status": "executed_exploratory" if len(validity) else "unavailable", "question": "물가·고용·성장·투자·금리 주제의 관계는 섹터마다 다른가?", "method": "Common topic lexicon, missing-topic preservation, sector IC and sector-conditioned macro features."},
        {"id": "disagreement", "status": "executed_exploratory" if len(resolutions) else "unavailable_insufficient_history", "question": "어조 괴리는 어느 쪽의 조정으로 축소되는가?", "method": "Expanding past-only standardization; |gap|≥1; next-quarter 25% gap reduction with origin scaling frozen."},
        {"id": "lead_lag", "status": "executed_exploratory" if len(leads) else "unavailable_insufficient_history", "question": "다른 출처의 어조를 추가하면 다음 어조 예측이 개선되는가?", "method": "Expanding OOS AR(1) vs AR(1)+other-source tone, both directions, overall and sectors."},
        {"id": "finbert", "status": "not_executed", "question": "전체 문서의 FinBERT가 LM보다 수익률을 더 잘 예측하는가?", "reason": "Return results use LM. The separate sampled-sentence agreement experiment is not a FinBERT return backtest; that comparison requires the identical full corpus and leakage-safe rerun."},
    ]
    findings = derive_findings(coverage,metrics,leads)
    sources = [{"name": "Federal Reserve FOMC calendars/minutes", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"}, {"name": "SEC EDGAR company filings", "url": "https://www.sec.gov/search-filings"}, {"name": "Ken French Data Library", "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"}, {"name": "Loughran-McDonald dictionaries", "url": "https://sraf.nd.edu/loughranmcdonald-master-dictionary/"}]
    return {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(), "status": "exploratory_pilot", "scope": "Current-constituent selected-sector pilot; not full S&P 500", "start": panel.formation_date.min() if len(panel) else None, "end": panel.formation_date.max() if len(panel) else None, "last_evaluated_formation": matched_panel.formation_date.max() if len(matched_panel) else None, "return_end": matched_panel.label_end.max() if len(matched_panel) else None, "method": "LM affect + quarterly 3-month returns + expanding OOS ridge", "ridge_alpha": 10., "min_train_quarters": 12, "horizon_months": 3}, "coverage": coverage, "modules": modules, "descriptive": descriptive_report(firms,fomc), "validity": {"overall": records(validity[validity.scope.eq("All")]) if len(validity) else [], "by_sector": records(validity[~validity.scope.eq("All")]) if len(validity) else []}, "models": records(metrics), "models_by_sector": records(sector_model_metrics(predictions)), "portfolios": records(portfolios), "disagreement": {"summary": resolution_counts, "lead_lag": records(leads), "events": records(resolutions), "notes": ["Fixed origin z-score scales; retrospective outcome labels are not investment inputs.", "Affect convergence is not proof of economic accuracy."]}, "topic_time_series": records(series), "findings": findings, "limitations": limitations, "sources": sources, "validation": {"folds": folds, "point_in_time": "All disclosure timestamps < final trading date 00:00 UTC. All training outcomes end strictly before test formation date.", "return_formula": "prod(1+stock_month_return)-prod(1+market_month_return), exact next 3 calendar months", "market": market_meta or {}}}


def run_analysis(project: Path, scope: str = "auto", reports_dir: Path | None = None,
                 private_dir: Path | None = None, final: bool = False) -> dict:
    """Freeze inputs per run; full checkpoint defaults never overwrite deliverables."""
    from .coverage import coverage_funnel
    project=Path(project)
    universe=pd.read_csv(project/"data/reference/selected_universe.csv")
    if scope=="auto":
        scope="full" if len(universe)>33 else "pilot"
    if scope not in ("pilot","full"):
        raise ValueError("scope must be auto, pilot or full")
    if scope=="pilot":
        pilot=json.loads((project/"configs/research.json").read_text(encoding="utf-8"))["pilot_tickers"]
        universe=universe[universe.ticker.isin(pilot)].copy()
    processed=project/"data/processed"
    private=Path(private_dir) if private_dir is not None else project/("data/private/full" if scope=="full" else "data/private")
    reports=Path(reports_dir) if reports_dir is not None else project/("reports" if final or scope=="pilot" else "reports/full_checkpoint")
    if scope=="full" and reports.resolve()==(project/"reports").resolve() and not final:
        raise ValueError("Full results require --final before replacing published reports")
    private.mkdir(parents=True,exist_ok=True)
    firms = pd.read_csv(processed/"firm_scores.csv")
    firms=firms[firms.ticker.isin(universe.ticker)].copy()
    fomc = pd.read_csv(processed/"fomc_scores.csv")
    collection=pd.read_csv(processed/"issuer_collection_status.csv").fillna("") if (processed/"issuer_collection_status.csv").exists() else pd.DataFrame()
    if len(collection):
        collection=collection[collection.ticker.isin(universe.ticker)]
    if final and scope=="full" and (len(collection)!=len(universe) or collection.status.isin(["pending","running"]).any()):
        raise ValueError("Final full-universe report requires all target collection attempts to finish")
    snapshots={"firm_scores":firms,"fomc_scores":fomc,"universe":universe,"collection_status":collection}
    input_manifest={}
    for name,data in snapshots.items():
        payload=data.to_csv(index=False,lineterminator="\n").encode("utf-8")
        (private/f"{name}_used.csv").write_bytes(payload)
        input_manifest[name]={"rows":len(data),"sha256":hashlib.sha256(payload).hexdigest()}
    monthly = pd.read_csv(private/"monthly_returns.csv")
    factors = pd.read_csv(private/"market_factors.csv")
    audit_path=private/"market_mapping_audit.csv"
    market_audit=pd.read_csv(audit_path).fillna("") if audit_path.exists() else pd.DataFrame()
    panel, exclusions = build_panel(firms,fomc,monthly,factors)
    validity = signal_validity(panel)
    predictions, folds = expanding_predictions(panel,include_ablation=True)
    main_predictions = predictions[~predictions.model.str.startswith("combined_without_")] if len(predictions) else predictions
    portfolios = portfolio_series(main_predictions)
    metrics = model_metrics(main_predictions, portfolios)
    sector_metrics = sector_model_metrics(main_predictions)
    ablation = topic_ablation_metrics(predictions)
    series = aggregate_text_series(panel)
    resolutions, leads = disagreement_analysis(series)
    market_meta_path = private/"market_manifest.json"
    market_meta = json.loads(market_meta_path.read_text(encoding="utf-8")) if market_meta_path.exists() else {}
    public_market_keys = {"source", "source_filename", "source_sha256", "factors_filename", "factors_sha256", "n_tickers", "n_rows", "exact_duplicate_rows_removed", "conflicting_duplicate_keys", "start", "end", "license", "mapping_status_counts", "target_tickers", "cache_reused"}
    public_market_meta = {k:v for k,v in market_meta.items() if k in public_market_keys}
    target_securities=len(pd.read_csv(project/"data/reference/universe_snapshot.csv")) if scope=="full" else len(universe)
    extra,funnel,issuer_status=coverage_funnel(universe,collection,firms,monthly,panel,main_predictions,market_audit,target_securities)
    extra.update(funnel_by_sector=records(funnel),issuer_status=records(issuer_status))
    report = build_report(firms,fomc,panel,exclusions,validity,main_predictions,portfolios,metrics,series,resolutions,leads,folds,public_market_meta,scope,extra)
    report["meta"].update(scope="full_current_constituents" if scope=="full" else "selected_33_issuer_pilot",
                          status="exploratory_full_current_universe" if scope=="full" and final else "exploratory_full_checkpoint" if scope=="full" else "exploratory_pilot",
                          final=final)
    report["validation"]["inputs"]=input_manifest
    if len(panel):
        report["descriptive"]["company_panel_coverage"] = records(panel.groupby(["ticker","sector"]).agg(
            formation_quarters=("formation_date","nunique"),return_observed=("excess_return","count"),
            first_formation=("formation_date","min"),last_formation=("formation_date","max")).reset_index())
    report["topic_ablation"] = records(ablation)
    report["validation"]["momentum_control"] = "Three completed calendar months ending one month before entry; entry-month return is unavailable at signal cutoff."
    report["validation"]["hac_lag_quarters"] = 1
    baseline_path=project/"reports/pilot_baseline.json"
    comparison=[]
    if scope=="full" and baseline_path.exists():
        baseline=json.loads(baseline_path.read_text(encoding="utf-8"))
        old={m["model"]:m for m in baseline["models"]}
        for metric in report["models"]:
            previous=old.get(metric["model"],{})
            for name in ("n_oos","n_periods","rmse","mean_ic","annualized_return","max_drawdown"):
                before,after=previous.get(name),metric.get(name)
                comparison.append({"model":metric["model"],"metric":name,"pilot":before,"full":after,
                                   "difference":after-before if before is not None and after is not None else None})
        report["pilot_comparison"]={"baseline_sha256":hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            "pilot_issuers":baseline["coverage"]["tickers"],"rows":comparison,
            "interpretation":"Same prespecified model and chronological rules; composition, data coverage, audited source-quality corrections (including pilot documents) and relative ridge penalty differ. The preserved pilot overlaps this sample and is not an independent holdout or causal sample-size experiment."}
    reports.mkdir(parents=True, exist_ok=True)
    for name, frame in [("panel",panel),("predictions",predictions)]:
        frame.to_csv(private/f"{name}.csv", index=False, lineterminator="\n")
    for name, frame in [("signal_validity",validity),("portfolios",portfolios),("model_metrics",metrics),("model_sector_metrics",sector_metrics),("topic_ablation",ablation),("topic_time_series",series),("disagreement_events",resolutions),("lead_lag",leads),("coverage_funnel",funnel),("issuer_coverage",issuer_status),("pilot_comparison",pd.DataFrame(comparison))]:
        frame.to_csv(reports/f"{name}.csv", index=False, lineterminator="\n")
    temporary_report = reports/"results.json.tmp"
    temporary_report.write_bytes(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8"))
    temporary_report.replace(reports/"results.json")
    return report
