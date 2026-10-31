"""Cross-check final public artifacts and independently recompute saved metrics."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]

def load(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))

def main():
    result=load('reports/results.json')
    snapshot=load('report-app/src/data.json')
    firms=pd.read_csv(ROOT/'data/processed/firm_scores.csv')
    fomc=pd.read_csv(ROOT/'data/processed/fomc_scores.csv')
    manifest=pd.read_csv(ROOT/'data/processed/source_manifest.csv')
    checks=[]
    def check(name,condition):
        if not bool(condition): raise AssertionError(name)
        checks.append(name)
    c=result['coverage']
    check('Corporate document count matches analysis',len(firms)==c['firm_documents'])
    check('FOMC document count matches analysis',len(fomc)==c['fomc_documents'])
    check('Company and sector counts match analysis',firms.ticker.nunique()==c['tickers'] and firms.sector.nunique()==c['sectors'])
    check('No duplicate scored document identities',not firms.doc_id.duplicated().any() and not fomc.doc_id.duplicated().any())
    check('Source manifest covers exactly the scored corpus',set(manifest.doc_id)==set(firms.doc_id)|set(fomc.doc_id) and not manifest.doc_id.duplicated().any())
    check('Original source links present',manifest.source_url.str.startswith('https://').all())
    check('Report snapshot uses the final results',snapshot['research']['results']==result)
    check('Report snapshot count matches final corpus',snapshot['research']['coverage']=={'fomc_documents':len(fomc),'firm_documents':len(firms),'companies':firms.ticker.nunique(),'sectors':firms.sector.nunique()})
    check('Report authoring status cleared',snapshot['buildStatus']=='complete')
    check('All four comparable models available',set(m['model'] for m in result['models'])=={'baseline','bottom_up','top_down','combined'})
    for model in result['models']:
        check(f"Model {model['model']} has genuine OOS observations",model['n_oos']>0 and model['n_periods']>0)
    ablation=result.get('topic_ablation',[])
    check('Overall ablation covers all five topics',{r['topic'] for r in ablation if r['scope']=='All'}=={'inflation','employment','growth','investment','rates'})
    fb=load('reports/finbert_method_comparison.json')
    fbrows=pd.read_csv(ROOT/'data/processed/finbert_method_sample.csv')
    check('FinBERT metadata matches saved documents',len(fbrows)==fb['documents'])
    check('FinBERT sample covers collected companies',fb['companies']==firms.ticker.nunique())
    check('No truncated sentences in the final FinBERT sample',fb.get('truncated_sentences',0)==0)
    # These calculations use saved records, not functions from the analysis engine.
    private=ROOT/'data/private'
    if (private/'predictions.csv').exists():
        pred=pd.read_csv(private/'predictions.csv')
        for model in result['models']:
            p=pred[pred.model.eq(model['model'])].dropna(subset=['prediction','excess_return'])
            rmse=float(np.sqrt(np.mean((p.prediction-p.excess_return)**2)))
            check(f"Independent RMSE recomputation: {model['model']}",np.isclose(rmse,model['rmse'],rtol=1e-10,atol=1e-9))
        panel=pd.read_csv(private/'panel.csv')
        cutoff=pd.to_datetime(panel.cutoff,utc=True)
        check('Every corporate source is strictly before signal cutoff',(pd.to_datetime(panel.firm_published_at,utc=True)<cutoff).all())
        check('Every FOMC source is strictly before signal cutoff',(pd.to_datetime(panel.fomc_published_at,utc=True)<cutoff).all())
        check('Every evaluated return ends after formation',(pd.to_datetime(pred.label_end)>pd.to_datetime(pred.formation_date)).all())
    portfolios=pd.read_csv(ROOT/'reports/portfolios.csv')
    for model in result['models']:
        vals=portfolios.loc[portfolios.model.eq(model['model']),'net_return'].dropna()
        if len(vals):
            annual=float(np.prod(1+vals)**(4/len(vals))-1)
            check(f"Independent annualized return recomputation: {model['model']}",np.isclose(annual,model['annualized_return'],rtol=1e-10,atol=1e-9))
    for name in ['proposal_7min','results_pilot']:
        path=ROOT/'presentations'/f'{name}.pptx'
        with zipfile.ZipFile(path) as archive:
            slides=[n for n in archive.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
            notes=[n for n in archive.namelist() if n.startswith('ppt/notesSlides/notesSlide') and n.endswith('.xml')]
            check(f'{name}: nine readable slide XML files',len(slides)==9 and all(ET.fromstring(archive.read(n)) is not None for n in slides))
            check(f'{name}: speaker notes on every slide',len(notes)==9)
    html=ROOT/'artifacts/result_report.html'
    check('Portable HTML artifact exists',html.exists() and html.stat().st_size>100_000)
    artifact_manifest=load('artifacts/report_manifest.json')
    for key,path in [('html_sha256',html),('snapshot_sha256',ROOT/'report-app/src/data.json'),('results_sha256',ROOT/'reports/results.json')]:
        check(f'Portable artifact fingerprint: {key}',hashlib.sha256(path.read_bytes()).hexdigest()==artifact_manifest[key])
    public={'status':'passed_with_visual_check_limitation','checked_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'html_sha256':hashlib.sha256(html.read_bytes()).hexdigest(),'results_sha256':hashlib.sha256((ROOT/'reports/results.json').read_bytes()).hexdigest(),'private_data_cross_checks_executed':(private/'predictions.csv').exists(),'browser_visual_verification':'Not performed: Computer Use policy stopped because the current browser URL could not be verified. Build, data consistency, and portable export verified separately.','powerpoint_visual_verification':'See docs/validation.md and the final native PowerPoint render review.'}
    (ROOT/'reports/validation_summary.json').write_text(json.dumps(public,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'{len(checks)} cross-artifact checks passed. Browser visual verification was not performed.')

if __name__=='__main__':
    main()
