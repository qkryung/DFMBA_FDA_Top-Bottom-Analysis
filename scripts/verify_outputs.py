"""Cross-check final public artifacts and independently recompute saved metrics."""
from __future__ import annotations
import hashlib
import json
import re
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
    firms=pd.read_csv(ROOT/'data/processed/firm_scores.csv',low_memory=False)
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
    authored=(ROOT/'report-app/src/content/report/ReportContent.jsx').read_text(encoding='utf-8')
    query_refs=set(re.findall(r'queryId="([^"]+)"',authored))|set(re.findall(r'rows\("([^"]+)"\)',authored))
    check('Every authored report query has saved reviewed data',query_refs.issubset(snapshot['queries']))
    corpus_counts={'fomc_documents':len(fomc),'firm_documents':len(firms),'companies':firms.ticker.nunique(),'sectors':firms.sector.nunique()}
    check('Report snapshot count matches final corpus',all(snapshot['research']['coverage'].get(k)==v for k,v in corpus_counts.items()))
    full=result['meta'].get('status')=='exploratory_full_current_universe'
    if full:
        universe=pd.read_csv(ROOT/'data/reference/universe_snapshot.csv')
        check('Full universe matches frozen securities and issuers',c['target_securities']==len(universe) and c['target_issuers']==universe.cik.nunique())
        protocol=load('reports/full_run_protocol.json')
        check('Constituent snapshot matches the frozen protocol',hashlib.sha256((ROOT/'data/reference/universe_snapshot.csv').read_bytes()).hexdigest()==protocol['universe_snapshot_sha256'])
        freeze=load('reports/corpus_freeze.json')
        check('Four source files match the frozen corpus bytes',len(freeze['input_sha256'])==4 and all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in freeze['input_sha256'].items()))
        check('Every target issuer was attempted',c['attempted_issuers']==c['target_issuers'])
        check('Coverage funnel counts are monotonic',c['target_issuers']>=c['document_issuers']>=c['market_matched_issuers']>=c['analysis_issuers']>=c['oos_issuers']>0)
        check('Collected issuer count matches scored corpus',c['document_issuers']==firms.ticker.nunique())
        selected=pd.read_csv(ROOT/'data/reference/selected_universe.csv')
        collection=pd.read_csv(ROOT/'data/processed/issuer_collection_status.csv').fillna('')
        inputs={'firm_scores':firms[firms.ticker.isin(selected.ticker)],'fomc_scores':fomc,
                'universe':selected,'collection_status':collection[collection.ticker.isin(selected.ticker)]}
        for name,frame in inputs.items():
            fingerprint=hashlib.sha256(frame.to_csv(index=False,lineterminator='\n').encode('utf-8')).hexdigest()
            expected=result['validation']['inputs'][name]
            check(f'Final analysis input identity: {name}',len(frame)==expected['rows'] and fingerprint==expected['sha256'])
        for key in ['target_securities','target_issuers','attempted_issuers','document_issuers','market_matched_issuers','analysis_issuers','oos_issuers','quarantined_issuers']:
            check(f'Report coverage agrees: {key}',snapshot['research']['coverage'][key]==c[key])
        funnel=pd.read_csv(ROOT/'reports/coverage_funnel.csv')
        for key in ['target_issuers','document_issuers','market_matched_issuers','analysis_issuers','oos_issuers']:
            check(f'Sector funnel reconciles: {key}',funnel[key].sum()==c[key])
        issuer=pd.read_csv(ROOT/'reports/issuer_coverage.csv')
        issuer_rows=snapshot['queries']['issuer_coverage']['rows']
        check('Report issuer explorer covers every target once',len(issuer_rows)==c['target_issuers'] and len({r['ticker'] for r in issuer_rows})==c['target_issuers'])
        check('Report issuer explorer reconciles document and evaluated counts',sum(r['documents'] for r in issuer_rows)==len(firms) and sum(bool(r['oos_included']) for r in issuer_rows)==c['oos_issuers'])
        check('Report issuer explorer matches public issuer audit',set(issuer.ticker)=={r['ticker'] for r in issuer_rows})
        baseline=load('reports/pilot_baseline.json')
        check('Preserved pilot baseline has its original scope',baseline['coverage']['tickers']==33 and baseline['coverage']['firm_documents']==1334)
        check('Pilot comparison exposes all four models',len(snapshot['queries']['pilot_comparison']['rows'])==4)
        repairs=load('reports/corpus_repairs_full.json')['repairs']
        pilot_ids=set(baseline['original_document_ids'])
        check('Repair pilot flags refer to the original document IDs',len(pilot_ids)==1334 and all(bool(r.get('was_in_original_pilot'))==(r['doc_id'] in pilot_ids) for r in repairs))
        terminal={'replaced_exhibit','extraction_scope_repaired','reviewed_retained','excluded_entire_filing'}
        check('Every confirmed corpus review has a resolved disposition',bool(repairs) and all(r.get('repair_status') in terminal for r in repairs))
        repair_summary=snapshot['queries']['corpus_repairs']['rows']
        check('Report repair summary reconciles with the audit ledger',sum(r['documents'] for r in repair_summary)==len(repairs) and sum(r['pilot_documents'] for r in repair_summary)==sum(bool(r.get('was_in_original_pilot')) for r in repairs))
        current_docs=set(firms.doc_id)
        check('Repair dispositions match final document inclusion',all((r['doc_id'] not in current_docs) if r['repair_status']=='excluded_entire_filing' else (r['doc_id'] in current_docs) for r in repairs))
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
    if full:
        fb_groups=snapshot['queries']['finbert_summary']['rows']
        check('FinBERT report separates corporate and FOMC corpora',set(r['source'] for r in fb_groups)=={'corporate','FOMC'} and sum(r['documents'] for r in fb_groups)==fb['documents'])
        latest=firms.sort_values('published_at').groupby('ticker').tail(1)
        expected_docs=set(latest.doc_id)|set(fomc.loc[fomc.meeting_date.str[:4].isin(['2024','2025']),'doc_id'])
        check('FinBERT uses final latest corporate documents and specified FOMC meetings',set(fbrows.doc_id)==expected_docs and not fbrows.doc_id.duplicated().any())
        current_text=pd.concat([firms[['doc_id','text_sha256']],fomc[['doc_id','text_sha256']]]).set_index('doc_id').text_sha256
        check('FinBERT text fingerprints match the final scored corpus',fbrows.apply(lambda r:current_text.get(r.doc_id)==r.text_sha256,axis=1).all())
    check('No truncated sentences in the final FinBERT sample',fb.get('truncated_sentences',0)==0)
    # These calculations use saved records, not functions from the analysis engine.
    private=ROOT/'data/private'/('full' if full else '')
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
        if len(vals) and model.get('annualized_return') is not None:
            annual=float(np.prod(1+vals)**(4/len(vals))-1)
            check(f"Independent annualized return recomputation: {model['model']}",np.isclose(annual,model['annualized_return'],rtol=1e-10,atol=1e-9))
    for name in ['proposal','results_pilot']+(['results_full'] if full else []):
        path=ROOT/'presentations'/f'{name}.pptx'
        expected_slides=6 if name=='proposal' else 9
        with zipfile.ZipFile(path) as archive:
            slides=[n for n in archive.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
            notes=[n for n in archive.namelist() if n.startswith('ppt/notesSlides/notesSlide') and n.endswith('.xml')]
            check(f'{name}: {expected_slides} readable slide XML files',len(slides)==expected_slides and all(ET.fromstring(archive.read(n)) is not None for n in slides))
            check(f'{name}: speaker notes on every slide',len(notes)==expected_slides)
    proposal=load('presentations/proposal_revision.json')
    check('Proposal manifest points to the current canonical PPT',proposal['file']=='presentations/proposal.pptx')
    check('Proposal manifest has six slides and 420-second timing',proposal['slides']==6 and len(proposal['slide_order'])==6 and proposal['seconds']==sum(s['seconds'] for s in proposal['slide_order'])==420)
    check('Proposal PPT fingerprint matches the reviewed artifact',hashlib.sha256((ROOT/proposal['file']).read_bytes()).hexdigest()==proposal['sha256'])
    check('Proposal PDF manifest describes the audited six-page export',proposal['pdf']['file']=='presentations/proposal.pdf' and proposal['pdf']['pages']==6)
    proposal_pdf=(ROOT/proposal['pdf']['file']).read_bytes()
    check('Proposal PDF fingerprint matches the audited export',proposal_pdf.startswith(b'%PDF-') and hashlib.sha256(proposal_pdf).hexdigest()==proposal['pdf']['sha256'])
    html=ROOT/'artifacts/result_report.html'
    check('Portable HTML artifact exists',html.exists() and html.stat().st_size>100_000)
    artifact_manifest=load('artifacts/report_manifest.json')
    for key,path in [('html_sha256',html),('snapshot_sha256',ROOT/'report-app/src/data.json'),('results_sha256',ROOT/'reports/results.json')]:
        check(f'Portable artifact fingerprint: {key}',hashlib.sha256(path.read_bytes()).hexdigest()==artifact_manifest[key])
    public={'status':'passed_with_visual_check_limitation','checked_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'html_sha256':hashlib.sha256(html.read_bytes()).hexdigest(),'results_sha256':hashlib.sha256((ROOT/'reports/results.json').read_bytes()).hexdigest(),'private_data_cross_checks_executed':(private/'predictions.csv').exists(),'browser_visual_verification':'Not performed: browser access host unavailable on retry. Earlier native browser access stopped because its URL could not be verified. Build, data consistency, and portable export verified separately.','powerpoint_visual_verification':'See docs/validation.md and the final native PowerPoint render review.'}
    (ROOT/'reports/validation_summary.json').write_text(json.dumps(public,indent=2,ensure_ascii=False),encoding='utf-8',newline='\n')
    print(f'{len(checks)} cross-artifact checks passed. Browser visual verification was not performed.')

if __name__=='__main__':
    main()
