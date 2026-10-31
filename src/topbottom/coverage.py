"""Issuer-denominator audit; public output deliberately excludes PERMNO."""
from __future__ import annotations

import pandas as pd


def coverage_funnel(universe, collection, firms, monthly, panel, predictions, market_audit=None,
                    target_securities=None):
    """Reconcile nested stages from the fixed target list, never from successes.

    Quarantine means a documented issuer cannot be linked to usable market
    history. Pending collection and issuers with no eligible documents are
    separate statuses, not quarantines. Analysis means at least one PIT panel
    observation; OOS means at least one forecast with an observed future return.
    """
    u=universe.copy()
    if u.ticker.duplicated().any():
        raise ValueError("Representative issuer universe must have unique tickers")
    if "issuer_id" not in u:
        u["issuer_id"]=u.get("cik",u.ticker).astype(str)
    if u.issuer_id.duplicated().any():
        raise ValueError("Representative universe must have one row per issuer")
    lookup=collection.set_index("ticker").to_dict("index") if collection is not None and len(collection) else {}
    audit=market_audit.set_index("ticker").to_dict("index") if market_audit is not None and len(market_audit) else {}
    doc_counts=firms.groupby("ticker").size().to_dict()
    market_tickers=set(monthly.ticker)
    analysis_tickers=set(panel.ticker) if len(panel) else set()
    oos_tickers=set(predictions.loc[predictions.excess_return.notna(),"ticker"]) if len(predictions) else set()
    unknown=set(doc_counts)-set(u.ticker)
    if unknown:
        raise ValueError(f"Scored issuers outside fixed universe: {sorted(unknown)}")
    rows=[]
    for source in u.to_dict("records"):
        ticker=source["ticker"]
        collected=lookup.get(ticker,{})
        mapping=audit.get(ticker,{})
        docs=int(doc_counts.get(ticker,0))
        status=str(collected.get("status","completed" if docs else "pending"))
        attempted=status not in ("pending","running") or docs>0
        # Running has begun an attempt, though final reports reject unfinished ledgers.
        attempted=attempted or status=="running"
        matched=ticker in market_tickers
        has_docs=docs>0
        if not attempted:
            exclusion="collection_pending"
        elif not has_docs:
            category=collected.get("error_category", "")
            category=str(category).strip() if pd.notna(category) else ""
            # Filing form describes a source, not why no usable document exists.
            # Empty CSV fields arrive as NaN, whose truthiness must not emit 'nan'.
            fallback={"completed":"no_eligible_documents", "completed_with_gaps":"no_eligible_documents",
                      "running":"collection_running"}.get(status,status)
            exclusion=category or fallback
        elif not matched:
            exclusion=str(mapping.get("mapping_status","no_usable_market_history"))
        elif ticker not in analysis_tickers:
            exclusion="no_eligible_quarterly_signal_price_pair"
        elif ticker not in oos_tickers:
            exclusion="no_observed_oos_return"
        else:
            exclusion="included"
        row={"issuer_id":str(source["issuer_id"]),"ticker":ticker,"company":source.get("company",source.get("security","")),
             "sector":source["sector"],"collection_status":status,"filing_regime":collected.get("filing_regime","unknown"),
             "documents":docs,"attempted":bool(attempted),"has_documents":has_docs,"market_matched":bool(has_docs and matched),
             "market_matched_all_target":matched,"analysis_included":ticker in analysis_tickers,"oos_included":ticker in oos_tickers,
             "quarantined":bool(has_docs and not matched),"exclusion_reason":exclusion,
             "mapping_status":mapping.get("mapping_status","matched_legacy_cache" if matched else "unavailable"),
             "market_history_start":mapping.get("market_history_start"),"market_history_end":mapping.get("market_history_end"),
             "mapping_reason":mapping.get("alias_reason", ""),"mapping_source_url":mapping.get("alias_source_url", ""),
             "first_study_period_filing":collected.get("first_study_period_filing"),"quarters_covered":collected.get("quarters_covered")}
        rows.append(row)
    issuer=pd.DataFrame(rows)
    stages={"attempted_issuers":"attempted","document_issuers":"has_documents","market_matched_issuers":"market_matched",
            "market_matched_issuers_all_target":"market_matched_all_target","analysis_issuers":"analysis_included",
            "oos_issuers":"oos_included","quarantined_issuers":"quarantined"}
    coverage={"target_issuers":len(u),"target_securities":int(target_securities if target_securities is not None else len(u)),
              **{name:int(issuer[col].sum()) for name,col in stages.items()},
              "pending_issuers":int(issuer.collection_status.eq("pending").sum()),
              "running_issuers":int(issuer.collection_status.eq("running").sum())}
    funnel=[]
    for sector,g in issuer.groupby("sector"):
        funnel.append({"sector":sector,"target_issuers":len(g),**{name:int(g[col].sum()) for name,col in stages.items()}})
    for group in [coverage]+funnel:
        ordered=[group[k] for k in ("oos_issuers","analysis_issuers","market_matched_issuers","document_issuers","attempted_issuers","target_issuers")]
        if ordered!=sorted(ordered):
            raise ValueError(f"Coverage stages do not reconcile: {group}")
    coverage["stage_definitions"]={"target":"Fixed current constituent issuers; one representative security per issuer.",
        "attempted":"Collection ledger is no longer pending; running attempts remain explicitly unfinished.",
        "document":"At least one scored, audited eligible corporate release.","market_matched":"Document issuer with a usable, identity-checked local market history.",
        "analysis":"At least one PIT quarterly panel row: available corporate/FOMC signals and observable entry-month market row. The next three-month return may still be missing or not yet observable; this is not a completed-return issuer count.",
        "oos":"At least one common-model OOS forecast paired with an observed, complete next-three-calendar-month return. Counts distinct issuers, not company-quarter observations.",
        "quarantined":"Document issuer excluded because market identity/data remains unresolved; separate from no-document issuers."}
    coverage["collection_status_counts"]={str(k):int(v) for k,v in issuer.collection_status.value_counts().items()}
    coverage["filing_regime_counts"]={str(k):int(v) for k,v in issuer.filing_regime.value_counts().items()}
    return coverage,pd.DataFrame(funnel),issuer
