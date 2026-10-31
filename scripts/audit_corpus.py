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
from topbottom.data import exclusion_reason,write_csv_atomic,write_coverage

def main():
    path=ROOT/'data/processed/firm_scores.csv'
    firms=pd.read_csv(path)
    retained=[]
    ledger=ROOT/'data/processed/excluded_exhibits.csv'
    excluded=pd.read_csv(ledger).to_dict('records') if ledger.exists() else []
    for row in firms.to_dict('records'):
        text=(ROOT/'data/raw/text'/(row['doc_id']+'.txt')).read_text(encoding='utf-8')
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
    timestamps=pd.to_datetime(firms.published_at,utc=True)
    if timestamps.isna().any():raise ValueError('Missing publication timestamp')
    if (firms.word_count<100).any():raise ValueError('Empty or near-empty company text')
    timestamp_checks,timestamp_mismatches=0,[]
    for row in firms.to_dict('records'):
        acc=row['accession']
        url=f"https://www.sec.gov/Archives/edgar/data/{int(row['cik'])}/{acc.replace('-','')}/{acc}-index.html"
        cached=ROOT/'data/raw/http'/(hashlib.sha256(url.encode()).hexdigest()+'.bin')
        if not cached.exists():continue
        page=BeautifulSoup(cached.read_bytes(),'html.parser').get_text(' ',strip=True)
        accepted=re.search(r'Accepted\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',page)
        if accepted:
            timestamp_checks+=1
            index_utc=pd.Timestamp(accepted.group(1)).tz_localize(ZoneInfo('America/New_York')).tz_convert('UTC')
            if index_utc != pd.Timestamp(row['published_at']):timestamp_mismatches.append(row['doc_id'])
    if timestamp_mismatches:raise ValueError(f'SEC API/index timestamp mismatch for {timestamp_mismatches}')
    for topic in ['inflation','employment','growth','investment','rates']:
        if not firms[f'topic_{topic}_tone'].isna().equals(firms[f'topic_{topic}_sentences'].eq(0)):
            raise ValueError(f'Inconsistent missing-topic score: {topic}')
    write_csv_atomic(firms,path)
    exclusion_frame=pd.DataFrame(excluded,columns=['doc_id','ticker','publication_date','source_url','reason']).drop_duplicates(['doc_id','reason'])
    # A changed rule can reinstate an exhibit; another exhibit of the same filing
    # can be retained while the original excluded exhibit remains in the ledger.
    retained_keys=set(zip(firms.doc_id,firms.source_url))
    exclusion_frame=exclusion_frame[[pair not in retained_keys for pair in zip(exclusion_frame.doc_id,exclusion_frame.source_url)]]
    write_csv_atomic(exclusion_frame,ledger)
    fed=pd.read_csv(ROOT/'data/processed/fomc_scores.csv')
    if fed.doc_id.duplicated().any():raise ValueError('Duplicate FOMC doc_id')
    if (pd.to_datetime(fed.published_at,utc=True).dt.tz_localize(None)<pd.to_datetime(fed.meeting_date)).any():raise ValueError('Minutes availability before meeting')
    config=json.loads((ROOT/'configs/research.json').read_text(encoding='utf-8'))
    report=write_coverage(ROOT,pd.read_csv(ROOT/'data/reference/selected_universe.csv'),config)
    report.update(excluded_nonrelease_exhibits=int(exclusion_frame.doc_id.nunique()),missing_timestamps=0,
                  timestamp_timezone='UTC',corpus_audit_passed=True,
                  sec_timestamp_crosschecks=timestamp_checks,sec_timestamp_mismatches=len(timestamp_mismatches),
                  topic_absence_policy='NaN tone when zero matching sentences; never imputed neutral')
    report['excluded_entire_filings']=int((~exclusion_frame.doc_id.isin(firms.doc_id)).sum())
    report['filings_with_replacement_exhibit']=int(exclusion_frame[exclusion_frame.doc_id.isin(firms.doc_id)].doc_id.nunique())
    quarter_counts=firms.assign(quarter=pd.to_datetime(firms.publication_date).dt.to_period('Q')).groupby('ticker').quarter.nunique()
    expected_quarters=4*(config['end_year']-config['start_year']+1)
    report['company_calendar_quarters_covered']=int(quarter_counts.sum())
    report['company_calendar_quarters_expected']=int(report['target_companies']*expected_quarters)
    report['each_company_covers_40_publication_quarters']=bool(quarter_counts.eq(expected_quarters).all())
    report['acquisition_log_note']='Unsupported or non-earnings candidate exhibits; not necessarily network errors. Some entries overlap entire-filing exclusions.'
    report['firm_topic_coverage']={topic:round(float((firms[f'topic_{topic}_sentences']>0).mean()),6) for topic in ['inflation','employment','growth','investment','rates']}
    report['fomc_text_scope']='Staff Review of the Economic Situation through before Committee Policy Action'
    (ROOT/'reports/data_coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    print(json.dumps({k:report[k] for k in ['covered_companies','firm_documents','fomc_documents','excluded_nonrelease_exhibits','corpus_audit_passed']},indent=2))

if __name__=='__main__':main()
