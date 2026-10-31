"""Replace the README result block from the saved, actual analysis outputs."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
MODEL_NAMES={'baseline':'기본 통제변수','bottom_up':'바텀업','top_down':'탑다운','combined':'결합'}

def fmt(v,d=3):
    return '—' if v is None else f'{v:.{d}f}'

def main():
    result=json.loads((ROOT/'reports/results.json').read_text(encoding='utf-8'))
    cov=result['coverage']
    fbpath=ROOT/'reports/finbert_method_comparison.json'
    fb=json.loads(fbpath.read_text(encoding='utf-8')) if fbpath.exists() else {}
    full=result['meta'].get('status')=='exploratory_full_current_universe'
    scope=(f"전수 수집 대상: **{cov['target_securities']}개 주식 클래스 / {cov['target_issuers']}개 기업**. "
           f"수집 시도 **{cov['attempted_issuers']}개**, 원문 확보 **{cov['document_issuers']}개**, 시장 자료 매칭 **{cov['market_matched_issuers']}개**, 분기 패널 포함 **{cov['analysis_issuers']}개**, 완결 수익률로 표본 외 평가에 포함된 기업 **{cov['oos_issuers']}개**입니다. "
           f"기업 문서 **{cov['firm_documents']:,}건**과 FOMC 의사록 **{cov['fomc_documents']}건**, **{cov['sectors']}개 섹터**를 포함합니다.") if full else f"실행 범위: **{cov['tickers']}개 기업 · {cov['sectors']}개 섹터 · 기업 문서 {cov['firm_documents']:,}건 · FOMC 의사록 {cov['fomc_documents']}건**."
    parts=[scope,
           f"분석 대상은 2016–2025년이며, 실제 평가 가능한 표본 외 구간은 **{cov['oos_periods']}개 분기**입니다. 원자료의 공개 시점과 결과가 완성된 수익률만 사용합니다.",
           '| 모델 | 평균 IC | 예측 오차(RMSE) | 평가 분기 |','|---|---:|---:|---:|']
    order={'baseline':0,'bottom_up':1,'top_down':2,'combined':3}
    for m in sorted(result.get('models',[]),key=lambda m:order.get(m.get('model'),99)):
        parts.append(f"| {MODEL_NAMES.get(m['model'],m['model'])} | {fmt(m.get('mean_ic'))} | {fmt(m.get('rmse'),4)} | {m.get('n_periods','—')} |")
    parts.append('')
    for finding in result.get('findings',[]):
        parts.append(f"- **{finding['title']}** {finding.get('text','')}")
    if full:
        portfolio=pd.read_csv(ROOT/'reports/portfolios.csv')
        observed=portfolio[portfolio.status.eq('observed')]
        first=(pd.Period(observed.formation_date.min()[:7],freq='M')+1).strftime('%Y-%m')
        last=(pd.Period(observed.formation_date.max()[:7],freq='M')+3).strftime('%Y-%m')
        periods=observed.formation_date.nunique()
        parts.extend(['',f"롱숏 투자성과는 실제 보유기간 **{first}~{last}, {periods}개 분기**입니다. 선택 종목의 수익률이 누락된 분기는 전체 포트폴리오를 미산출 처리했으며, 수익률을 0으로 채우거나 나머지 종목으로 재가중하지 않았습니다. 예측 오차·IC의 평가 기간 및 기존 파일럿의 투자성과 평가 기간과 구분합니다."])
    if fb.get('status')=='executed':
        parts.extend(['',f"LM·FinBERT 동일 문장 비교: **{fb['documents']}개 문서 · {fb['sentences']:,}개 문장**. 전체 코퍼스의 투자 수익률 비교는 수행하지 않았습니다."])
    parts.extend(['','정확한 수치와 근거는 [분석 결과 JSON](reports/results.json), [수집 현황](reports/data_coverage.json), HTML·결과 PPT에서 확인할 수 있습니다.'])
    text=(ROOT/'README.md').read_text(encoding='utf-8')
    start='<!-- RESULTS:START -->'
    end='<!-- RESULTS:END -->'
    if text.count(start)!=1 or text.count(end)!=1:
        raise ValueError('Expected exactly one generated result block in README')
    before,rest=text.split(start)
    _,after=rest.split(end)
    (ROOT/'README.md').write_text(before+start+'\n'+'\n\n'.join(parts[:2])+'\n\n'+'\n'.join(parts[2:])+'\n'+end+after,encoding='utf-8',newline='\n')
    print('README result block updated from reports/results.json')

if __name__=='__main__':
    main()
