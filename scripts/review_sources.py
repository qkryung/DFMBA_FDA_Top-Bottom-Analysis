"""Create a local-only source review queue; never auto-reject by headline keywords."""
import re
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
firms=pd.read_csv(ROOT/'data/processed/firm_scores.csv')
financial_headline=re.compile(r'(?:reports?|announces?|releases?).{0,160}(?:quarter|financial results|earnings|guidance|outlook)|(?:quarter|year.end|full.year).{0,120}(?:results|earnings|performance)|earnings release|financial results',re.I)
transaction_headline=re.compile(r'acquisition|acquires?|merger|transaction|settlement|conference|investor (?:day|presentation)|pro forma|recast|restatement|divestiture',re.I)
rows=[]
for row in firms.to_dict('records'):
 text=(ROOT/'data/raw/text'/(row['doc_id']+'.txt')).read_text(encoding='utf-8')
 reasons=[]
 if row['word_count']<200 or row['sentence_count']<=2:reasons.append('short_or_sparse_narrative')
 if not financial_headline.search(text[:800]):reasons.append('no_obvious_earnings_headline')
 if transaction_headline.search(text[:400]) and not financial_headline.search(text[:400]):reasons.append('possible_other_event')
 if row['word_count']>20000:reasons.append('very_long_annual_report_or_supplement')
 if reasons:rows.append({k:row[k] for k in ('ticker','doc_id','publication_date','source_url','word_count','sentence_count')}|{'review_flags':'|'.join(reasons),'opening_for_local_review':text[:1200]})
pd.DataFrame(rows).to_csv(ROOT/'data/raw/source_review_flags.csv',index=False,lineterminator='\n')
print(f'Flagged {len(rows)}/{len(firms)} documents for local review; flags are not exclusions.')
print(pd.DataFrame(rows)['review_flags'].value_counts().to_string() if rows else '')
