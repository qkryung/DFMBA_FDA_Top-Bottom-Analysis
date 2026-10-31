"""Review source grain, timestamp coverage and non-release exhibit exclusions."""
import json
import hashlib
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from topbottom.data import exclusion_reason,write_csv_atomic,write_coverage,write_json_atomic,write_manifest,conservative_ir_available_at,HTML_PARSER

def main():
    path=ROOT/'data/processed/firm_scores.csv'
    pending_status=ROOT/'data/processed/issuer_collection_status.csv'
    if pending_status.exists() and pd.read_csv(pending_status).status.isin(['pending','running']).any():
        raise RuntimeError('Complete the running issuer collection before mutating the audited corpus.')
    firms=pd.read_csv(path,low_memory=False)
    retained=[]
    ledger=ROOT/'data/processed/excluded_exhibits.csv'
    excluded=pd.read_csv(ledger).to_dict('records') if ledger.exists() else []
    for row in firms.to_dict('records'):
        text=(ROOT/'data/raw/text'/(row['doc_id']+'.txt')).read_text(encoding='utf-8')
        if hashlib.sha256(text.encode()).hexdigest() != row['text_sha256']:
            raise ValueError(f"Raw-text hash differs from score input: {row['doc_id']}")
        reason=exclusion_reason(text,row['source_url'])
        if reason:
            excluded.append({k:row[k] for k in ['doc_id','ticker','publication_date','source_url']}|{'reason':reason})
        else:retained.append(row)
    firms=pd.DataFrame(retained)
    firms=firms.sort_values('published_at')
    repeated=firms.duplicated(['ticker','text_sha256'],keep='first')
    for row in firms[repeated].to_dict('records'):
        excluded.append({k:row[k] for k in ['doc_id','ticker','publication_date','source_url']}|{'reason':'Duplicate extracted earnings-release text; earliest SEC availability retained'})
    firms=firms[~repeated].copy()
    if firms.doc_id.duplicated().any():raise ValueError('Duplicate doc_id in company corpus')
    if 'sec_acceptance_at' not in firms:
        firms['sec_acceptance_at']=firms.published_at
    else:
        missing_sec=firms.sec_acceptance_at.isna()
        if (missing_sec & firms.document_type.astype(str).str.startswith('official_IR_')).any():raise ValueError('IR replacement is missing its original SEC acceptance timestamp')
        firms.loc[missing_sec,'sec_acceptance_at']=firms.loc[missing_sec,'published_at']
    timestamps=pd.to_datetime(firms.published_at,utc=True,format='ISO8601')
    if timestamps.isna().any():raise ValueError('Missing publication timestamp')
    if ((firms.word_count<100)|(firms.sentence_count<=2)).any():raise ValueError('Insufficient analyzable company narrative; recover an alternative exhibit before audit')
    timestamp_checks,timestamp_mismatches=0,[]
    for row in firms.to_dict('records'):
        acc=row['accession']
        url=f"https://www.sec.gov/Archives/edgar/data/{int(row['cik'])}/{acc.replace('-','')}/{acc}-index.html"
        cached=ROOT/'data/raw/http'/(hashlib.sha256(url.encode()).hexdigest()+'.bin')
        if not cached.exists():continue
        page=BeautifulSoup(cached.read_bytes(),HTML_PARSER).get_text(' ',strip=True)
        accepted=re.search(r'Accepted\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',page)
        if accepted:
            timestamp_checks+=1
            index_utc=pd.Timestamp(accepted.group(1)).tz_localize(ZoneInfo('America/New_York')).tz_convert('UTC')
            sec_time = row.get('sec_acceptance_at')
            if pd.isna(sec_time):sec_time=row['published_at']
            if index_utc != pd.Timestamp(sec_time):timestamp_mismatches.append(row['doc_id'])
            if str(row.get('document_type','')).startswith('official_IR_'):
                expected=conservative_ir_available_at(sec_time,row['official_IR_release_date'])
                if pd.Timestamp(expected)!=pd.Timestamp(row['published_at']):raise ValueError(f"Invalid conservative IR availability: {row['doc_id']}")
    if timestamp_mismatches:raise ValueError(f'SEC API/index timestamp mismatch for {timestamp_mismatches}')
    if timestamp_checks != len(firms):raise ValueError(f'SEC acceptance timestamp crosscheck incomplete: {timestamp_checks}/{len(firms)}')
    for topic in ['inflation','employment','growth','investment','rates']:
        if not firms[f'topic_{topic}_tone'].isna().equals(firms[f'topic_{topic}_sentences'].eq(0)):
            raise ValueError(f'Inconsistent missing-topic score: {topic}')
    selected=pd.read_csv(ROOT/'data/reference/selected_universe.csv')
    failure_path=ROOT/'data/processed/acquisition_failures.csv'
    failures=pd.read_csv(failure_path)
    retained_accessions={(row['ticker'],row['accession']):row for row in firms.to_dict('records')}
    for i,failure in failures.iterrows():
        replacement=retained_accessions.get((failure.ticker,failure.accession))
        failures.loc[i,'resolved_by_alternative_source']=bool(replacement)
        if replacement:
            failures.loc[i,'resolution_source_url']=replacement['source_url']
            failures.loc[i,'resolution_document_type']=replacement['document_type']
    write_csv_atomic(failures,failure_path)
    issuer_ids=selected.set_index('ticker')['issuer_id' if 'issuer_id' in selected else 'current_snapshot_cik'].to_dict()
    firms['issuer_id']=firms.ticker.map(issuer_ids).astype(int)
    write_csv_atomic(firms,path)
    exclusion_frame=pd.DataFrame(excluded,columns=['doc_id','ticker','publication_date','source_url','reason']).drop_duplicates(['doc_id','source_url','reason'])
    # A changed rule can reinstate an exhibit; another exhibit of the same filing
    # can be retained while the original excluded exhibit remains in the ledger.
    retained_keys=set(zip(firms.doc_id,firms.source_url))
    exclusion_frame=exclusion_frame[[pair not in retained_keys for pair in zip(exclusion_frame.doc_id,exclusion_frame.source_url)]]
    write_csv_atomic(exclusion_frame,ledger)
    fed=pd.read_csv(ROOT/'data/processed/fomc_scores.csv')
    if fed.doc_id.duplicated().any():raise ValueError('Duplicate FOMC doc_id')
    for row in fed.to_dict('records'):
        text=(ROOT/'data/raw/text'/(row['doc_id']+'.txt')).read_text(encoding='utf-8')
        if hashlib.sha256(text.encode()).hexdigest()!=row['text_sha256']:raise ValueError(f"FOMC source hash mismatch: {row['doc_id']}")
    if (pd.to_datetime(fed.published_at,utc=True).dt.tz_localize(None)<pd.to_datetime(fed.meeting_date)).any():raise ValueError('Minutes availability before meeting')
    config=json.loads((ROOT/'configs/research.json').read_text(encoding='utf-8'))
    selected=pd.read_csv(ROOT/'data/reference/selected_universe.csv')
    status_path=ROOT/'data/processed/issuer_collection_status.csv'
    if status_path.exists():
        statuses=pd.read_csv(status_path)
        identities=json.loads((ROOT/'configs/market_identity.json').read_text(encoding='utf-8')) if (ROOT/'configs/market_identity.json').exists() else {}
        for i,status in statuses.iterrows():
            subset=firms[firms.ticker.eq(status.ticker)]
            issuer_failures=failures[failures.ticker.eq(status.ticker)]
            unresolved=issuer_failures[~issuer_failures.resolved_by_alternative_source.fillna(False).astype(bool)]
            statuses.loc[i,'documents']=len(subset)
            statuses.loc[i,'quarters_covered']=pd.to_datetime(subset.publication_date).dt.to_period('Q').nunique()
            statuses.loc[i,'first_publication']=subset.publication_date.min() if len(subset) else None
            statuses.loc[i,'last_publication']=subset.publication_date.max() if len(subset) else None
            statuses.loc[i,'failed_candidates']=len(unresolved)
            statuses.loc[i,'error_category']='|'.join(sorted(set(unresolved.error_category.dropna())))
            statuses.loc[i,'candidate_filings']=len(set(subset.accession.dropna())|set(issuer_failures.accession.dropna()))
            if len(subset):
                statuses.loc[i,'status']='completed' if statuses.loc[i,'quarters_covered'] >= 4*(config['end_year']-config['start_year']+1) else 'completed_with_gaps'
            elif len(unresolved) and status.status!='submissions_error':
                statuses.loc[i,'status']='no_qualifying_earnings_documents'
            if status.ticker in identities.get('unavailable',{}) and len(subset)==0:
                statuses.loc[i,'status']='not_yet_listed_in_study_period'
                statuses.loc[i,'history_note']=identities['unavailable'][status.ticker]['reason']
                statuses.loc[i,'history_source_url']=identities['unavailable'][status.ticker]['source_url']
            # Persist the audited retained set so a later resumed collection cannot
            # resurrect a rejected or duplicate exhibit from an older checkpoint.
            checkpoint=ROOT/'data/raw/issuer_checkpoints'/f"{int(status.issuer_id)}_{config['start_year']}_{config['end_year']}.json"
            if checkpoint.exists():
                saved=json.loads(checkpoint.read_text(encoding='utf-8'))
                saved['records']=subset.to_dict('records')
                saved['failures']=issuer_failures.to_dict('records')
                saved['status']=statuses.loc[i].to_dict()
                saved['corpus_audited']=True
                write_json_atomic(saved,checkpoint)
        write_csv_atomic(statuses,status_path)
    write_manifest(ROOT)
    report=write_coverage(ROOT,selected,config)
    report.update(excluded_nonrelease_exhibits=int(exclusion_frame.doc_id.nunique()),missing_timestamps=0,
                  timestamp_timezone='UTC',corpus_audit_passed=True,
                  sec_timestamp_crosschecks=timestamp_checks,sec_timestamp_mismatches=len(timestamp_mismatches),
                  topic_absence_policy='NaN tone when zero matching sentences; never imputed neutral')
    report['excluded_entire_filings']=int(exclusion_frame.loc[~exclusion_frame.doc_id.isin(firms.doc_id),'doc_id'].nunique())
    report['filings_with_replacement_exhibit']=int(exclusion_frame[exclusion_frame.doc_id.isin(firms.doc_id)].doc_id.nunique())
    report['exclusion_count_basis']='Distinct filing/doc IDs with a rejected source: entire-filing exclusions plus filings with retained replacement sources. Not a count of every alternate exhibit URL.'
    quarter_counts=firms.assign(quarter=pd.to_datetime(firms.publication_date).dt.to_period('Q')).groupby('ticker').quarter.nunique()
    expected_quarters=4*(config['end_year']-config['start_year']+1)
    report['company_calendar_quarters_covered']=int(quarter_counts.sum())
    report['company_calendar_quarters_expected']=int(report['target_companies']*expected_quarters)
    report['company_calendar_quarters_maximum']=int(report['target_companies']*expected_quarters)
    report['quarter_coverage_denominator_note']='The Cartesian maximum assumes every current issuer existed throughout the study. Pre-IPO, pre-spin-off and successor-history quarters are not automatically missing observations.'
    report['each_company_covers_40_publication_quarters']=bool(len(quarter_counts)==len(selected) and quarter_counts.eq(expected_quarters).all())
    report['each_company_covers_all_publication_quarters']=bool(len(quarter_counts)==len(selected) and quarter_counts.eq(expected_quarters).all())
    quarters=pd.period_range(f"{config['start_year']}Q1",f"{config['end_year']}Q4",freq='Q').astype(str)
    grid=pd.MultiIndex.from_product([selected.ticker,quarters],names=['ticker','publication_quarter'])
    counts=firms.assign(publication_quarter=pd.to_datetime(firms.publication_date).dt.to_period('Q').astype(str)).groupby(['ticker','publication_quarter']).size()
    quarter_table=counts.reindex(grid,fill_value=0).rename('documents').reset_index().merge(selected[['ticker','sector','issuer_id']],on='ticker',how='left')
    write_csv_atomic(quarter_table,ROOT/'data/processed/coverage_by_company_quarter.csv')
    if report['target_companies']>len(config['pilot_tickers']):
        report['all_target_issuers_attempted']=report['attempted_companies']==report['target_companies']
        report['status']='executed_full_universe' if report['all_target_issuers_attempted'] else 'full_collection_in_progress'
    report['acquisition_log_note']='Unsupported or non-earnings candidate exhibits; not necessarily network errors. Some entries overlap entire-filing exclusions.'
    report['acquisition_failure_attempts']=len(failures)
    report['resolved_acquisition_candidates']=int(failures.resolved_by_alternative_source.fillna(False).sum())
    report['unresolved_acquisition_candidates']=len(failures)-report['resolved_acquisition_candidates']
    report['document_type_counts']=firms.document_type.value_counts().to_dict()
    report['official_IR_date_only_availability_documents']=int(firms.document_type.astype(str).str.startswith('official_IR_').sum())
    report['official_IR_availability_rule']='For actual IR text replacements: max(original SEC acceptance, midnight America/New_York following the official IR release date). SEC acceptance retained separately; PDF metadata is only a version check.'
    report['source_audit_scope']='Whole-corpus automated source/hash/timestamp/topic checks plus risk-targeted manual inspections and bounded source repairs. Not every document was manually read in full.'
    repair_path=ROOT/'reports/corpus_repairs_full.json'
    if repair_path.exists():
        repair_ledger=json.loads(repair_path.read_text(encoding='utf-8'))
        baseline_path=ROOT/'reports/pilot_baseline.json'
        original_pilot_ids=set(json.loads(baseline_path.read_text(encoding='utf-8')).get('original_document_ids',[])) if baseline_path.exists() else set()
        retained_by_id=firms.set_index('doc_id').to_dict('index')
        for repair in repair_ledger['repairs']:
            repair['was_in_original_pilot']=repair['doc_id'] in original_pilot_ids
            new=retained_by_id.get(repair['doc_id'])
            if new is None:
                repair['repair_status']='excluded_entire_filing'
            else:
                repair['repair_status']='replaced_exhibit' if new['source_url'] != repair['old_source_url'] else 'extraction_scope_repaired' if new['text_sha256'] != repair['old_text_sha256'] else 'reviewed_retained'
                repair.update(new_source_url=new['source_url'],new_text_sha256=new['text_sha256'],new_word_count=int(new['word_count']))
        repair_ledger['final_audit_complete']=True
        repair_ledger['unresolved_repairs']=0
        write_json_atomic(repair_ledger,repair_path)
        report['source_repair_status_counts']=pd.Series([r['repair_status'] for r in repair_ledger['repairs']]).value_counts().to_dict()
        report['unresolved_source_repairs']=0
    report['firm_topic_coverage']={topic:round(float((firms[f'topic_{topic}_sentences']>0).mean()),6) for topic in ['inflation','employment','growth','investment','rates']}
    report['fomc_text_scope']='Staff Review of the Economic Situation through before Committee Policy Action'
    (ROOT/'reports/data_coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    recovery_summary_path=ROOT/'reports/source_recovery_summary.json'
    if recovery_summary_path.exists():
        recovery_summary=json.loads(recovery_summary_path.read_text(encoding='utf-8'))
        recovery_summary.update(final_audited_firm_documents=len(firms),final_audited_fomc_documents=len(fed),final_audited_companies=int(firms.ticker.nunique()),final_audit_report='reports/data_coverage.json',final_audit_completed_at=report['updated_at'])
        write_json_atomic(recovery_summary,recovery_summary_path)
    print(json.dumps({k:report[k] for k in ['covered_companies','firm_documents','fomc_documents','excluded_nonrelease_exhibits','corpus_audit_passed']},indent=2))

if __name__=='__main__':main()
