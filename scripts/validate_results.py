"""Independently check saved results with standard-library calculations.

Run after collection/audit/analysis completes. Requires local data/private files;
the saved check summary contains no company-level market observations.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def shift_month(date, offset):
    year, month = map(int, date[:7].split("-"))
    ordinal = year*12+month-1+offset
    return f"{ordinal//12:04d}-{ordinal%12+1:02d}"


def main():
    report = json.loads((ROOT/"reports/results.json").read_text(encoding="utf-8"))
    firms = read_rows(ROOT/"data/processed/firm_scores.csv")
    fomc = read_rows(ROOT/"data/processed/fomc_scores.csv")
    panel = read_rows(ROOT/"data/private/panel.csv")
    predictions = read_rows(ROOT/"data/private/predictions.csv")
    stock_rows = read_rows(ROOT/"data/private/monthly_returns.csv")
    factor_rows = read_rows(ROOT/"data/private/market_factors.csv")
    stock = {(r["ticker"],r["month"]):number(r["return"]) for r in stock_rows}
    market = {r["month"]:number(r["market_return"]) for r in factor_rows}
    company_docs = defaultdict(list)
    for row in firms:
        company_docs[row["ticker"].replace("-", ".")].append(row)
    checks=[]

    def check(name, passed, observations):
        checks.append({"name":name,"status":"pass" if passed else "fail","observations":observations})

    check("Final report matches current collected corpus",report["coverage"]["firm_documents"]==len(firms) and report["coverage"]["fomc_documents"]==len(fomc),len(firms)+len(fomc))
    check("Unique company-quarter panel",len({(r["ticker"],r["formation_date"]) for r in panel})==len(panel),len(panel))
    check("Unique security-month market input",len(stock)==len(stock_rows),len(stock_rows))
    wrong_availability=wrong_selection=wrong_returns=wrong_momentum=wrong_scores=0
    return_errors=[]
    for row in panel:
        cutoff=stamp(row["cutoff"])
        firm_date,macro_date=stamp(row["firm_published_at"]),stamp(row["fomc_published_at"])
        wrong_availability += int(not(firm_date<cutoff and macro_date<cutoff and cutoff-firm_date<=timedelta(days=120)))
        eligible=[d for d in company_docs[row["ticker"]] if cutoff-timedelta(days=120)<=stamp(d["published_at"])<cutoff]
        latest=max(eligible,key=lambda d:(stamp(d["published_at"]),d["doc_id"])) if eligible else None
        eligible_macro=[d for d in fomc if stamp(d["published_at"])<cutoff]
        latest_macro=max(eligible_macro,key=lambda d:(stamp(d["published_at"]),d["doc_id"])) if eligible_macro else None
        wrong_selection += int(latest is None or latest["doc_id"]!=row["firm_doc_id"] or latest_macro is None or latest_macro["doc_id"]!=row["fomc_doc_id"])
        for prefix, source in (("bu",latest),("td",latest_macro)):
            if source is None:
                wrong_scores+=1
                continue
            columns=["tone","uncertainty_rate","forward_tone"]+[f"topic_{t}_tone" for t in ("inflation","employment","growth","investment","rates")]
            for column in columns:
                expected,actual=number(source.get(column)),number(row.get(f"{prefix}_{column}"))
                if math.isfinite(expected):
                    wrong_scores += int(not math.isfinite(actual) or abs(expected-actual)>1e-10)
                else:
                    wrong_scores += int(math.isfinite(actual))
        future=[shift_month(row["formation_date"],k) for k in (1,2,3)]
        sr=[stock.get((row["ticker"],m),float("nan")) for m in future]
        mr=[market.get(m,float("nan")) for m in future]
        target=number(row["excess_return"])
        if all(math.isfinite(x) for x in sr+mr):
            expected=math.prod(1+x for x in sr)-math.prod(1+x for x in mr)
            error=abs(target-expected)
            return_errors.append(error)
            wrong_returns += int(not math.isfinite(error) or error>1e-10)
        else:
            wrong_returns += int(math.isfinite(target))
        prior=[shift_month(row["formation_date"],k) for k in (-3,-2,-1)]
        returns=[stock.get((row["ticker"],m),float("nan")) for m in prior]
        momentum=number(row["momentum"])
        if all(math.isfinite(x) for x in returns):
            expected=math.prod(1+x for x in returns)-1
            wrong_momentum += int(not math.isfinite(momentum) or abs(momentum-expected)>1e-10)
        else:
            wrong_momentum += int(math.isfinite(momentum))
    check("All source timestamps precede entry-day cutoff and satisfy age",wrong_availability==0,len(panel))
    check("Selected documents independently equal latest eligible releases",wrong_selection==0,len(panel))
    check("Saved panel scores match current source-score files",wrong_scores==0,len(panel)*16)
    check("Independent exact-calendar BHAR recomputation and missing outcomes",wrong_returns==0,len(panel))
    check("Independent lagged-momentum recomputation excludes entry month",wrong_momentum==0,len(panel))
    folds=report["validation"]["folds"]
    check("All reported training outcomes matured before forecast cutoff",all(f["latest_label_end"]<f["test_date"] for f in folds),len(folds))
    keysets=defaultdict(set)
    for row in predictions:
        keysets[row["model"]].add((row["ticker"],row["formation_date"]))
    check("All models and topic ablations use the same OOS rows",len({frozenset(s) for s in keysets.values()})<=1,len(keysets))
    wrong_rmse=0
    for metric in report["models"]:
        pairs=[r for r in predictions if r["model"]==metric["model"] and math.isfinite(number(r["excess_return"]))]
        if pairs:
            rmse=math.sqrt(sum((number(r["prediction"])-number(r["excess_return"]))**2 for r in pairs)/len(pairs))
            wrong_rmse += int(abs(rmse-metric["rmse"])>1e-8)
        else:
            wrong_rmse += int(metric["rmse"] is not None)
    check("Independent saved-prediction RMSE matches public model metrics",wrong_rmse==0,len(report["models"]))
    check("Public market metadata excludes security identifier mapping","ticker_mapping" not in report["validation"]["market"],1)
    output={"generated_at":datetime.now(timezone.utc).isoformat(),"status":"pass" if all(c["status"]=="pass" for c in checks) else "fail",
            "checks":checks,"n_checks":len(checks),"max_independent_return_error":max(return_errors) if return_errors else None,
            "scope":"Numerical/source-timing checks of saved analysis; does not validate topic semantics, eliminate survivorship bias, or verify rendered artifacts."}
    (ROOT/"reports/analysis_validation.json").write_bytes(json.dumps(output,indent=2).encode("utf-8"))
    print(f"{output['status'].upper()}: {sum(c['status']=='pass' for c in checks)}/{len(checks)} independent analysis checks")
    for c in checks:
        if c["status"]!="pass":
            print(f"FAIL: {c['name']}")
    raise SystemExit(0 if output["status"]=="pass" else 1)


if __name__ == "__main__":
    main()
