"""Conservative, cached mapping of a fixed current universe to local CRSP history.

Never infer issuer identity from name similarity or choose among ambiguous active
securities by market cap. Any identifier-level audit remains in data/private.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


def ticker_key(value):
    return str(value).upper().strip().replace("-", ".")


def _signature(path):
    stat=path.stat()
    return {"path":str(path.resolve()),"size":stat.st_size,"mtime_ns":stat.st_mtime_ns}


def prepare_market(crsp_path: Path, factors_path: Path, tickers: list[str], output_dir: Path,
                   aliases: dict | None = None, force: bool = False, unavailable: dict | None = None) -> dict:
    """Prepare all target securities once, then reuse unchanged local inputs.

    aliases is an explicitly researched target->source ticker mapping, with a
    reason and supporting source_url for every entry. Automatic fuzzy/name-based
    matches are deliberately unavailable. Historical ticker reuse alone is not
    evidence that a historical security belongs to today's issuer.
    """
    crsp_path,factors_path,output_dir=map(Path,(crsp_path,factors_path,output_dir))
    aliases=aliases or {}
    unavailable=unavailable or {}
    targets=sorted(set(map(ticker_key,tickers)))
    for target,override in aliases.items():
        if not all(override.get(k) for k in ("source_ticker","reason","source_url")):
            raise ValueError(f"Market alias {target} requires source_ticker, reason and source_url")
    signature={"schema_version":3,"crsp":_signature(crsp_path),"factors":_signature(factors_path),"targets":targets,"aliases":aliases,"unavailable":unavailable}
    manifest_path=output_dir/"market_manifest.json"
    if not force and manifest_path.exists() and all((output_dir/f).exists() for f in ("monthly_returns.csv","market_factors.csv","market_mapping_audit.csv")):
        cached=json.loads(manifest_path.read_text(encoding="utf-8"))
        if cached.get("preparation_signature")==signature:
            return {**cached,"cache_reused":True}
    output_dir.mkdir(parents=True,exist_ok=True)
    cols=["PERMNO","Ticker","MthCalDt","MthRet","MthPrc","ShrOut"]
    available=pd.read_csv(crsp_path,nrows=0).columns
    identity_cols=[c for c in ("SecurityNm","IssuerNm","SecurityType","ShareType") if c in available]
    endpoints,history=[],[]
    lookup_targets=set(targets)|{ticker_key(v["source_ticker"]) for v in aliases.values()}
    source_end=""
    for chunk in pd.read_csv(crsp_path,usecols=cols+identity_cols,chunksize=200_000):
        chunk["Ticker"]=chunk.Ticker.map(ticker_key)
        source_end=max(source_end,str(chunk.MthCalDt.max()))
        last=chunk.groupby("PERMNO").MthCalDt.transform("max")
        endpoints.append(chunk[chunk.MthCalDt.eq(last)][["PERMNO","Ticker","MthCalDt"]+identity_cols].drop_duplicates())
        target_rows=chunk[chunk.Ticker.isin(lookup_targets)]
        if len(target_rows):
            history.append(target_rows.groupby(["PERMNO","Ticker"]).MthCalDt.agg(["min","max"]).reset_index())
    endpoints=pd.concat(endpoints,ignore_index=True).drop_duplicates()
    endpoints=endpoints[endpoints.MthCalDt.eq(endpoints.groupby("PERMNO").MthCalDt.transform("max"))]
    histories=pd.concat(history,ignore_index=True) if history else pd.DataFrame(columns=["PERMNO","Ticker","min","max"])
    mapping_rows=[]
    for target in targets:
        alias=aliases.get(target,{})
        source_ticker=ticker_key(alias.get("source_ticker",target))
        active=endpoints[endpoints.Ticker.eq(source_ticker) & endpoints.MthCalDt.eq(source_end)]
        if alias.get("security_name"):
            active=active[active.SecurityNm.str.strip().eq(alias["security_name"].strip())]
        historical=histories[histories.Ticker.eq(source_ticker)]
        row={"ticker":target,"source_ticker":source_ticker,"mapping_status":"ticker_not_found","permno":None,
             "candidate_securities":int(active.PERMNO.nunique()),"source_last_month":source_end[:7],
             "alias_reason":alias.get("reason",""),"alias_source_url":alias.get("source_url","")}
        if active.PERMNO.nunique()==1:
            row.update(mapping_status="matched_explicit_alias" if alias else "matched_exact_active",permno=int(active.PERMNO.iloc[0]))
            row.update({k:str(active.iloc[0][k]) for k in identity_cols})
        elif active.PERMNO.nunique()>1:
            row["mapping_status"]="ambiguous_active_ticker"
        elif len(historical):
            hist_permnos=set(historical.PERMNO)
            still_active=endpoints[endpoints.PERMNO.isin(hist_permnos) & endpoints.MthCalDt.eq(source_end)]
            row["mapping_status"]="historical_ticker_endpoint_differs" if len(still_active) else "inactive_before_source_end"
        if target in unavailable:
            evidence=unavailable[target]
            if not evidence.get("reason") or not evidence.get("source_url"):
                raise ValueError("Known unavailable issuer requires source evidence")
            row.update(mapping_status="not_listed_in_market_study_period",permno=None,
                       alias_reason=evidence["reason"],alias_source_url=evidence["source_url"])
        if row["permno"] is not None and "SecurityType" in row and row["SecurityType"]!="EQTY":
            row.update(mapping_status="non_equity_identity_conflict",permno=None)
        mapping_rows.append(row)
    audit=pd.DataFrame(mapping_rows)
    # Two current issuers may not silently inherit the same PERMNO.
    chosen=audit[audit.permno.notna()]
    shared=set(chosen.loc[chosen.permno.duplicated(keep=False),"permno"])
    if shared:
        audit.loc[audit.permno.isin(shared),"mapping_status"]="shared_security_conflict"
        audit.loc[audit.permno.isin(shared),"permno"]=None
    mapping={int(r.permno):r.ticker for r in audit.itertuples() if pd.notna(r.permno)}
    frames=[]
    for chunk in pd.read_csv(crsp_path,usecols=cols,chunksize=200_000):
        x=chunk[chunk.PERMNO.isin(mapping)].copy()
        x["ticker"]=x.PERMNO.map(mapping)
        frames.append(x)
    raw=pd.concat(frames,ignore_index=True).rename(columns={"MthCalDt":"date","MthRet":"return","PERMNO":"permno"})
    raw["return"]=pd.to_numeric(raw["return"],errors="coerce")
    raw["market_cap"]=pd.to_numeric(raw.MthPrc,errors="coerce").abs()*pd.to_numeric(raw.ShrOut,errors="coerce")
    raw["date"]=pd.to_datetime(raw.date)
    raw["month"]=raw.date.dt.to_period("M").astype(str)
    monthly=raw[["ticker","permno","date","month","return","market_cap"]].sort_values(["ticker","date"])
    duplicate_rows=int(monthly.duplicated().sum())
    monthly=monthly.drop_duplicates()
    conflict=monthly.duplicated(["ticker","month"],keep=False)
    conflict_keys=int(monthly.loc[conflict,["ticker","month"]].drop_duplicates().shape[0])
    conflict_tickers=set(monthly.loc[conflict,"ticker"])
    if conflict_tickers:
        monthly.loc[conflict].to_csv(output_dir/"market_conflicting_rows.csv",index=False,lineterminator="\n")
        audit.loc[audit.ticker.isin(conflict_tickers),"mapping_status"]="conflicting_monthly_rows"
        monthly=monthly[~monthly.ticker.isin(conflict_tickers)]
    invalid=monthly["return"].lt(-1)
    if invalid.any():
        invalid_tickers=set(monthly.loc[invalid,"ticker"])
        audit.loc[audit.ticker.isin(invalid_tickers),"mapping_status"]="invalid_return_domain"
        monthly=monthly[~monthly.ticker.isin(invalid_tickers)]
    for ticker,g in monthly.groupby("ticker"):
        mask=audit.ticker.eq(ticker)
        audit.loc[mask,"market_history_start"]=g.month.min()
        audit.loc[mask,"market_history_end"]=g.month.max()
        audit.loc[mask,"market_months"]=len(g)
    # Exactly six-digit monthly FF records, excluding annual footer rows.
    rows=[]
    for line in factors_path.read_text(encoding="utf-8-sig").splitlines():
        parts=line.split(",")
        if len(parts)>=5 and len(parts[0].strip())==6 and parts[0].strip().isdigit():
            try:
                values=list(map(float,parts[1:5]))
            except ValueError:
                continue
            ym=parts[0].strip()
            rows.append({"month":f"{ym[:4]}-{ym[4:]}","market_return":(values[0]+values[3])/100,
                         "mkt_rf":values[0]/100,"smb":values[1]/100,"hml":values[2]/100,"rf":values[3]/100})
    factors=pd.DataFrame(rows)
    if factors.month.duplicated().any():
        raise ValueError("Duplicate Fama French month keys")
    monthly.to_csv(output_dir/"monthly_returns.csv",index=False,lineterminator="\n")
    factors.to_csv(output_dir/"market_factors.csv",index=False,lineterminator="\n")
    audit.to_csv(output_dir/"market_mapping_audit.csv",index=False,lineterminator="\n")
    endpoints.to_csv(output_dir/"security_endpoints.csv",index=False,lineterminator="\n")
    with crsp_path.open("rb") as stream:
        crsp_hash=hashlib.file_digest(stream,"sha256").hexdigest()
    with factors_path.open("rb") as stream:
        factors_hash=hashlib.file_digest(stream,"sha256").hexdigest()
    meta={"source":"Local classroom CRSP CIZ monthly total returns; Ken French monthly factors",
          "source_filename":crsp_path.name,"source_sha256":crsp_hash,"factors_filename":factors_path.name,"factors_sha256":factors_hash,
          "target_tickers":len(targets),"n_tickers":int(monthly.ticker.nunique()),"missing_tickers":sorted(set(targets)-set(monthly.ticker)),
          "n_rows":len(monthly),"exact_duplicate_rows_removed":duplicate_rows,"conflicting_duplicate_keys":conflict_keys,
          "quarantined_tickers":sorted(audit.loc[~audit.mapping_status.str.startswith("matched_"),"ticker"]),
          "mapping_status_counts":{str(k):int(v) for k,v in audit.mapping_status.value_counts().items()},
          "start":str(monthly.date.min().date()) if len(monthly) else None,"end":str(monthly.date.max().date()) if len(monthly) else None,
          "source_end":source_end,"cache_reused":False,"preparation_signature":signature,
          "license":"Local use only; no security-level source/derived return rows or PERMNO mapping in public outputs."}
    manifest_path.write_bytes(json.dumps(meta,ensure_ascii=False,indent=2).encode("utf-8"))
    return meta
