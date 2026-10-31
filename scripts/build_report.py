"""Build the report snapshot from actual saved outputs, without network or fixtures."""
from __future__ import annotations
import argparse, hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'report-app'
TOPICS = {'inflation':'물가','employment':'고용','growth':'성장·수요','investment':'투자','rates':'금리·금융여건'}
SECTORS = {'Information Technology':'정보기술','Health Care':'헬스케어','Financials':'금융','Consumer Discretionary':'경기소비재','Consumer Staples':'필수소비재','Industrials':'산업재','Energy':'에너지','Materials':'소재','Utilities':'유틸리티','Real Estate':'부동산','Communication Services':'커뮤니케이션'}

def read_csv(name):
    p=ROOT/name
    try:
        return pd.read_csv(p,low_memory=False) if p.exists() and p.stat().st_size else pd.DataFrame()
    except pd.errors.EmptyDataError:
        return pd.DataFrame()

def clean(v):
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,list): return [clean(x) for x in v]
    if isinstance(v,float) and not math.isfinite(v): return None
    return v

def query(rows,label,files,definitions=None,caveats=None):
    return {'rows':clean(rows),'source':{'label':label,'files':files,'filters':caveats or [],'metricDefinitions':definitions or [],'evidenceFlow':[{'title':'재현 방법','detail':'수집·분석·보고서 생성 명령은 README.md에 설명되어 있습니다. 계산은 scripts/ 및 src/topbottom/에 보관합니다.'}]}}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--complete', action='store_true', help='Mark the report ready for delivery after analysis and QA.')
    args=parser.parse_args()
    p=ROOT/'reports/results.json'
    result=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    old=json.loads((APP/'src/data.json').read_text(encoding='utf-8'))
    fomc=read_csv('data/processed/fomc_scores.csv')
    firms=read_csv('data/processed/firm_scores.csv')
    if firms.empty: firms=read_csv('data/processed/earnings_scores.csv')
    if args.complete:
        saved=result.get('coverage',{})
        observed={'firm_documents':len(firms),'fomc_documents':len(fomc),'tickers':int(firms.ticker.nunique()) if 'ticker' in firms else 0}
        if any(saved.get(k)!=v for k,v in observed.items()):
            raise ValueError('Final report refused: source corpus and saved analysis counts differ. Complete corpus audit and rerun final analysis first.')
        if result.get('meta',{}).get('status') not in ('exploratory_pilot','exploratory_full_current_universe'):
            raise ValueError('Final report requires a finalized analysis, not a full-collection checkpoint.')
        if result.get('meta',{}).get('status') == 'exploratory_full_current_universe':
            universe=read_csv('data/reference/selected_universe.csv')
            collection=read_csv('data/processed/issuer_collection_status.csv').fillna('')
            inputs={'firm_scores':firms[firms.ticker.isin(universe.ticker)],
                    'fomc_scores':fomc,'universe':universe,
                    'collection_status':collection[collection.ticker.isin(universe.ticker)]}
            expected=result.get('validation',{}).get('inputs',{})
            for name,frame in inputs.items():
                fingerprint=hashlib.sha256(frame.to_csv(index=False,lineterminator='\n').encode('utf-8')).hexdigest()
                if expected.get(name,{}).get('sha256') != fingerprint:
                    raise ValueError(f'Final report refused: {name} differs from the finalized analysis input. Rerun analysis after corpus changes.')
    tone,topics=[],[]
    for _,r in fomc.iterrows():
        date=str(r.get('publication_date',r.get('published_at','')))[:10]
        tone.append({'date':date,'tone':r.get('tone'),'uncertainty':r.get('uncertainty_rate')})
        for key,label in TOPICS.items():
            topics.append({'date':date,'topic':label,'tone':r.get(f'topic_{key}_tone'),'topicShare':r.get(f'topic_{key}_share'),'sentences':r.get(f'topic_{key}_sentences')})
    sectors=[]
    if not firms.empty and 'sector' in firms:
        for sector,g in firms.groupby('sector'):
            sectors.append({'sector':sector,'label':SECTORS.get(sector,sector),'documents':len(g),'companies':g.ticker.nunique(),'tone':float(g.tone.mean()),'uncertainty':float(g.uncertainty_rate.mean())})
    order={'baseline':0,'bottom_up':1,'top_down':2,'combined':3}
    models=sorted(result.get('models',[]),key=lambda m:order.get(m.get('model'),99))
    plan=[{'stage':i+1,'question':q} for i,q in enumerate(['기업의 어조는 수익률을 예측하는가?','연준 인식을 결합하면 개선되는가?','어떤 거시 주제가 중요한가?','괴리가 생기면 어느 쪽이 선행하는가?'])]
    queries={
      'research_plan':query(plan,'Case 3 기반 연구 설계',['docs/research_plan.md']),
      'fomc_tone':query(tone,'Federal Reserve 의사록 · LM 금융 사전',['data/processed/fomc_scores.csv'],[{'label':'어조 점수','definition':'(긍정 단어 수 − 부정 단어 수) / 전체 단어 수 × 100. 정책 기조와 다름.'},{'label':'불확실성','definition':'LM 불확실성 단어 수 / 전체 단어 수 × 100.'}]),
      'fomc_topics':query(topics,'FOMC 주제별 문장 분석',['data/processed/fomc_scores.csv'],[{'label':'주제 비중','definition':'해당 주제 문장 / 전체 문장. 복수 태깅이므로 비중 합은 100%가 아닐 수 있음.'}],['규칙 기반 복수 분류. 주제 미언급은 결측.']),
      'sector_coverage':query(sectors,'SEC 실적 발표 자료 확보 범위',['data/processed/firm_scores.csv'],caveats=['현재 구성종목 기반 표본. 과거 S&P 500 전체를 대표하지 않음.']),
      'models':query(models,'시간 순서 표본 외 모델 비교',['reports/results.json'],caveats=result.get('limitations',[])),
      'findings':query(result.get('findings',[]),'저장된 분석 결과에 따른 주요 해석',['reports/results.json'],caveats=['현재 구성기업·제한된 평가 분기에서 얻은 탐색적 결과.']),
      'gap_summary':query(result.get('disagreement',{}).get('summary',[]),'괴리 해소 유형 탐색',['reports/results.json']),
      'lead_lag':query(result.get('disagreement',{}).get('lead_lag',[]),'인식 선후행 비교',['reports/results.json']),
      'models_by_sector':query(result.get('models_by_sector',[]),'섹터별 예측 모형 비교',['reports/results.json']),
      'topic_ablation':query(result.get('topic_ablation',[]),'주제별 추가 예측력 비교',['reports/results.json'])
    }
    yearly=[]
    if not firms.empty:
        dated=firms.assign(year=pd.to_datetime(firms.publication_date).dt.year)
        for year,g in dated.groupby('year'):
            yearly.append({'year':str(year),'companies':int(g.ticker.nunique()),'documents':len(g)})
    queries['yearly_coverage']=query(yearly,'공개 연도별 실적 원문 확보 기업 수',['data/processed/firm_scores.csv'],caveats=['연중 한 건 이상 원문을 확보한 기업 수. 매 분기 분석 가능 기업 수와 다름.'])
    repair_path=ROOT/'reports/corpus_repairs_full.json'
    repair_records=json.loads(repair_path.read_text(encoding='utf-8')).get('repairs',[]) if repair_path.exists() else []
    repair_labels={'replaced_exhibit':'정상 실적 첨부로 교체','extraction_scope_repaired':'본문 추출 범위 교정','reviewed_retained':'검토 후 유지','excluded_entire_filing':'범위 밖 문서 제외'}
    repair_summary=[{'status':key,'label':label,'documents':sum(r.get('repair_status')==key for r in repair_records),'pilot_documents':sum(r.get('repair_status')==key and bool(r.get('was_in_original_pilot')) for r in repair_records)} for key,label in repair_labels.items()]
    queries['corpus_repairs']=query(repair_summary,'원문 범위·첨부 선택 검토 및 처리 기록',['reports/corpus_repairs_full.json'],caveats=['자동 규칙과 표제 선별 후 확인한 의심 사례의 처리 현황. 모든 원문 전문의 수동 전수검수를 뜻하지 않음.'])
    for name in ['model_metrics','signal_validity','portfolios','topic_time_series']:
        df=read_csv(f'reports/{name}.csv')
        queries[name]=query(df.to_dict('records'),f'분석 결과 · {name}',[f'reports/{name}.csv'])
    portfolio=read_csv('reports/portfolios.csv')
    portfolio_calendar=[]
    if not portfolio.empty:
        for model,g in portfolio.groupby('model'):
            observed=g[g.status.eq('observed') & g.net_return.notna()].sort_values('formation_date')
            if len(observed):
                first=pd.Period(str(observed.iloc[0].formation_date)[:7],freq='M')
                last=pd.Period(str(observed.iloc[-1].formation_date)[:7],freq='M')
                portfolio_calendar.append({'model':model,'periods':len(observed),
                    'holding_start':(first+1).start_time.date().isoformat(),
                    'holding_end':(last+3).end_time.date().isoformat(),
                    'missing_selected_periods':int(g.status.eq('missing_selected_returns').sum())})
    queries['portfolio_calendar']=query(portfolio_calendar,'투자성과가 완결된 포트폴리오 평가 기간',['reports/portfolios.csv'],caveats=['선택 종목의 수익률이 누락된 분기는 재가중하거나 0으로 채우지 않고 포트폴리오 전체를 미산출 처리. 예측 오차와 평가 기간이 다를 수 있음.'])
    curve=[]
    if not portfolio.empty:
        wide={}
        model_stats={m['model']:m for m in models}
        for model,g in portfolio.groupby('model'):
            # The analysis suppresses compounding when portfolio calendars have
            # gaps or differ across models. Do not reconnect missing periods.
            if model_stats.get(model,{}).get('annualized_return') is None:
                continue
            wealth=1.0
            g=g.dropna(subset=['net_return']).sort_values('formation_date')
            if g.empty: continue
            start=str(g.iloc[0]['formation_date'])[:10]
            wide.setdefault(start,{'date':start})[model]=wealth
            for _,r in g.sort_values('formation_date').iterrows():
                if pd.isna(r.get('net_return')): continue
                wealth*=1+float(r['net_return'])
                date=(pd.Timestamp(r['formation_date']).to_period('Q')+1).end_time.date().isoformat()
                wide.setdefault(date,{'date':date})[model]=wealth
        curve=[wide[d] for d in sorted(wide)]
    queries['portfolio_growth']=query(curve,'분기 재조정 롱숏 포트폴리오 · 거래비용 차감',['reports/portfolios.csv'],[{'label':'누적 가치','definition':'첫 편입일 가치 1에 분기 순수익률을 연속 복리 적용. 이후 x축은 수익률 관측이 완료된 보유 분기의 달력상 말일.'}],['롱 100%·숏 100%, 거래대금당 10bp. 대차료·자금조달·시장충격 제외.'])
    cov={'fomc_documents':len(fomc),'firm_documents':len(firms),'companies':int(firms.ticker.nunique()) if 'ticker' in firms else 0,'sectors':len(sectors)}
    for key in ['target_securities','target_issuers','attempted_issuers','document_issuers','market_matched_issuers','analysis_issuers','oos_issuers','quarantined_issuers']:
        if key in result.get('coverage',{}):
            cov[key]=result['coverage'][key]
    funnel=read_csv('reports/coverage_funnel.csv')
    queries['coverage_funnel']=query(funnel.to_dict('records'),'기업 모집단에서 실제 분석까지의 커버리지',['reports/coverage_funnel.csv','reports/results.json'],caveats=['현재 구성기업 기준. 과거의 실제 S&P 500 구성종목을 재현한 표본이 아님.'])
    issuer_coverage=read_csv('reports/issuer_coverage.csv')
    public_columns=['ticker','company','sector','documents','quarters_covered','has_documents','market_matched','analysis_included','oos_included','collection_status','exclusion_reason']
    issuer_rows=issuer_coverage[[c for c in public_columns if c in issuer_coverage]].to_dict('records') if not issuer_coverage.empty else []
    queries['issuer_coverage']=query(issuer_rows,'500개 대상 기업의 자료 확보와 분석 포함 여부',['reports/issuer_coverage.csv'],[{'label':'자료 분기','definition':'실적 자료의 공개 날짜 기준 분기 수. 회계 분기나 완결된 미래 수익률 관측 수와 다름.'},{'label':'분석 포함','definition':'공개 시점이 맞는 텍스트 신호와 진입 월 시장 자료가 연결된 관측이 한 건 이상 있음.'},{'label':'표본 외 평가','definition':'모형의 표본 외 예측과 완결된 미래 수익률이 연결된 관측이 한 건 이상 있음.'}],['표본 외 포함 기업도 모든 분기에 관측되는 것은 아님.'])
    baseline_path=ROOT/'reports/pilot_baseline.json'
    baseline=json.loads(baseline_path.read_text(encoding='utf-8')) if baseline_path.exists() else {}
    comparisons=[]
    if result.get('meta',{}).get('status')=='exploratory_full_current_universe':
        pilot_models={m['model']:m for m in baseline.get('models',[])}
        for m in models:
            p=pilot_models.get(m['model'],{})
            comparisons.append({'model':m['model'],'pilot_mean_ic':p.get('mean_ic'),'full_mean_ic':m.get('mean_ic'),'pilot_rmse':p.get('rmse'),'full_rmse':m.get('rmse'),'pilot_n_oos':p.get('n_oos'),'full_n_oos':m.get('n_oos')})
    queries['pilot_comparison']=query(comparisons,'33개 기업 파일럿과 현재 구성기업 전수 분석 비교',['reports/pilot_baseline.json','reports/results.json'],caveats=['표본 확대와 추가 원문 검토에 따른 자료 교정을 포함한 기술적 비교. 성과 차이의 인과효과 추정이나 독립 검증이 아님.'])
    roadmap_path=ROOT/'reports/development_roadmap.json'
    roadmap=json.loads(roadmap_path.read_text(encoding='utf-8')) if roadmap_path.exists() else {}
    queries['development_roadmap']=query(roadmap.get('stages',[]),'추가 개발 우선순위와 검증 기준',['reports/development_roadmap.json','docs/development_roadmap.md'],caveats=['후속 연구 제안이며 실행 완료된 분석 결과가 아님.'])
    fb_path=ROOT/'reports/finbert_method_comparison.json'
    fb=json.loads(fb_path.read_text(encoding='utf-8')) if fb_path.exists() else {}
    queries['finbert_sample']=query(read_csv('data/processed/finbert_method_sample.csv').to_dict('records'),'같은 문장 표본의 LM·FinBERT 점수 비교',['data/processed/finbert_method_sample.csv'])
    fb_sources=[dict(source=k,**v) for k,v in fb.get('by_corpus',fb.get('by_source',{})).items()]
    queries['finbert_summary']=query(fb_sources,'자료 출처별 LM·FinBERT 문서 점수 일치도',['reports/finbert_method_comparison.json'],caveats=['동일 문장으로 집계한 문서 점수의 순위상관. 정확도나 수익률 예측력 아님.'])
    snap={'id':old['id'],'surface':'report','title':'연준의 말, 기업의 말','status':'observed-research','buildStatus':'complete' if args.complete else 'updating','generatedAt':datetime.now(timezone.utc).isoformat(),'exportPreferences':{'selected':None,'destinations':[]},'report':{},'research':{'results':result,'coverage':cov,'topics':TOPICS,'sectors':SECTORS,'finbert':fb,'pilot':baseline,'roadmap':roadmap},'queries':queries}
    payload=json.dumps(clean(snap),ensure_ascii=False,indent=2,allow_nan=False,default=int)
    (APP/'src/data.json').write_text(payload,encoding='utf-8',newline='\n')
    (ROOT/'reports/app_snapshot.json').write_text(payload,encoding='utf-8',newline='\n')
    print(json.dumps(cov))

if __name__=='__main__':main()
