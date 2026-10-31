"""Build the report snapshot from actual saved outputs, without network or fixtures."""
from __future__ import annotations
import argparse, json, math
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
        return pd.read_csv(p) if p.exists() and p.stat().st_size else pd.DataFrame()
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
      'sector_coverage':query(sectors,'SEC 실적 보도자료 확보 범위',['data/processed/firm_scores.csv'],caveats=['현재 구성종목 기반 표본. 과거 S&P 500 전체를 대표하지 않음.']),
      'models':query(models,'시간 순서 표본 외 모델 비교',['reports/results.json'],caveats=result.get('limitations',[])),
      'gap_summary':query(result.get('disagreement',{}).get('summary',[]),'괴리 해소 유형 탐색',['reports/results.json']),
      'lead_lag':query(result.get('disagreement',{}).get('lead_lag',[]),'인식 선후행 비교',['reports/results.json']),
      'models_by_sector':query(result.get('models_by_sector',[]),'섹터별 예측 모형 비교',['reports/results.json']),
      'topic_ablation':query(result.get('topic_ablation',[]),'주제별 추가 예측력 비교',['reports/results.json'])
    }
    for name in ['model_metrics','signal_validity','portfolios','topic_time_series']:
        df=read_csv(f'reports/{name}.csv')
        queries[name]=query(df.to_dict('records'),f'분석 결과 · {name}',[f'reports/{name}.csv'])
    portfolio=read_csv('reports/portfolios.csv')
    curve=[]
    if not portfolio.empty:
        wide={}
        for model,g in portfolio.groupby('model'):
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
    fb_path=ROOT/'reports/finbert_method_comparison.json'
    fb=json.loads(fb_path.read_text(encoding='utf-8')) if fb_path.exists() else {}
    queries['finbert_sample']=query(read_csv('data/processed/finbert_method_sample.csv').to_dict('records'),'같은 문장 표본의 LM·FinBERT 점수 비교',['data/processed/finbert_method_sample.csv'])
    fb_sources=[dict(source=k,**v) for k,v in fb.get('by_source',{}).items()]
    queries['finbert_summary']=query(fb_sources,'자료 출처별 LM·FinBERT 문서 점수 일치도',['reports/finbert_method_comparison.json'],caveats=['동일 문장으로 집계한 문서 점수의 순위상관. 정확도나 수익률 예측력 아님.'])
    snap={'id':old['id'],'surface':'report','title':'연준의 말, 기업의 말','status':'observed-research','buildStatus':'complete' if args.complete else 'updating','generatedAt':datetime.now(timezone.utc).isoformat(),'exportPreferences':{'selected':None,'destinations':[]},'report':{},'research':{'results':result,'coverage':cov,'topics':TOPICS,'sectors':SECTORS,'finbert':fb},'queries':queries}
    payload=json.dumps(clean(snap),ensure_ascii=False,indent=2,allow_nan=False,default=int)
    (APP/'src/data.json').write_text(payload,encoding='utf-8',newline='\n')
    (ROOT/'reports/app_snapshot.json').write_text(payload,encoding='utf-8',newline='\n')
    print(json.dumps(cov))

if __name__=='__main__':main()
