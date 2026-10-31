import React, {useState} from "react";
import {EvidenceChart,DataComponent,RichNarrative,useDataApp} from "../../data-app-public.jsx";
import "./report.css";

const num=v=>v==null?"—":Number(v).toLocaleString("ko-KR");
const fmt=(v,d=3)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toFixed(d);
const modelNames={baseline:"기본 통제변수",bottom_up:"바텀업",top_down:"탑다운",combined:"결합",combined_topics:"주제 결합",topic_combined:"주제 결합"};
const signalNames={bu_tone:"전체 어조",bu_uncertainty_rate:"불확실성",bu_forward_tone:"미래 전망",bu_topic_inflation_tone:"물가",bu_topic_employment_tone:"고용",bu_topic_growth_tone:"성장·수요",bu_topic_investment_tone:"투자",bu_topic_rates_tone:"금리·금융여건"};
const outcomes={persistent_or_diverging:"지속·확대 / 축소 미달",both_adjust:"양측 조정",corporate_toward_fed:"기업이 연준 쪽으로",fed_toward_corporate:"연준이 기업 쪽으로"};
const stages=[["01","기업의 말","실적·가이던스 어조와 이후 수익률의 관계를 먼저 확인합니다."],["02","연준의 말 더하기","같은 시점의 FOMC 인식을 결합해 추가 예측력을 검증합니다."],["03","주제와 섹터","물가·고용·성장·투자 등 주제별 차이를 전체와 섹터에서 비교합니다."],["04","괴리와 선행성","어느 쪽 인식이 뒤따라 움직이는지, 투자에도 유용한지 확인합니다."]];
function Prose({id,children}){return <RichNarrative id={id} value={children}/>}
function Empty({children}){return <div className="tb-empty">{children}</div>}

export function ReportContent(){
 const {snapshot,reviewedRows}=useDataApp();
 const [topic,setTopic]=useState("물가"),[metric,setMetric]=useState("tone"),[sector,setSector]=useState("All"),[gapTopic,setGapTopic]=useState("overall");
 const res=snapshot.research?.results||{},cov=snapshot.research?.coverage||{};
 const rows=id=>reviewedRows(id),models=rows("models"),sectors=rows("sector_coverage");
 const topics=Object.values(snapshot.research?.topics||{}),topicRows=rows("fomc_topics").filter(r=>r.topic===topic);
 const valid=rows("signal_validity").filter(r=>r.scope===sector);
 const gap=rows("gap_summary").filter(r=>r.scope===sector&&r.topic===gapTopic).map(r=>({...r,label:outcomes[r.outcome]||r.outcome}));
 const leads=rows("lead_lag").filter(r=>r.scope===sector&&r.topic===gapTopic);
 const ablation=rows("topic_ablation").filter(r=>r.scope===sector);
 const sectorModels=rows("models_by_sector").filter(r=>r.sector===sector);
 const fb=snapshot.research?.finbert||{};
 return <article className="report-page tb-report" aria-label="FOMC와 기업 텍스트 연구 보고서">
  <header className="tb-hero"><div className="tb-eyebrow">KAIST DFMBA · FINANCIAL DATA ANALYTICS</div><h1>연준의 말,<br/><span>기업의 말.</span></h1>
   <Prose id="tb:intro">탑다운과 바텀업의 텍스트를 결합하면 투자 판단이 나아질까요? Case 3의 공시 수집·문장 추출에서 출발한 미국 주식 연구입니다.</Prose>
   <div className="tb-hero-links"><a href="https://github.com/qkryung/DFMBA_FDA_Top-Bottom-Analysis" target="_blank" rel="noreferrer">GitHub에서 프로젝트 보기 ↗</a><a href="https://github.com/qkryung/DFMBA_FDA_Top-Bottom-Analysis/blob/main/presentations/proposal_7min.pptx" target="_blank" rel="noreferrer">7분 제안 발표 PPT ↗</a></div>
  </header>
  <nav className="tb-nav" aria-label="보고서 목차"><a href="#tb-results">결과 요약</a><a href="#tb-questions">연구 흐름</a><a href="#tb-data">수집 범위</a><a href="#tb-macro">주제 분석</a><a href="#tb-models">투자 검증</a><a href="#tb-methods">방법과 한계</a></nav>
  <section id="tb-results" className="tb-section"><div className="tb-section-label">RESEARCH READOUT</div><h2>실제 데이터로 확인한 내용</h2><div className="tb-status">{res.meta?.status==="exploratory_pilot"?"실제 자료를 사용한 탐색적 파일럿":res.meta?.status||"자료 수집·분석 진행 중"}</div>
   {(res.findings||[]).length?res.findings.map((f,i)=><Prose key={i} id={`tb:finding:${i}`}>{`### ${f.title}\n\n${f.text||f.detail||""}`}</Prose>):<Prose id="tb:pending">공식 원문을 수집하고 분석 결과를 연결하고 있습니다. 아래 커버리지는 실제 확보한 자료이며, 투자 성과는 검증이 끝난 결과만 표시합니다.</Prose>}
   <div className="tb-kpis" data-reviewed-rows>{[["FOMC 의사록",cov.fomc_documents,"건"],["기업 실적 자료",cov.firm_documents,"건"],["실제 분석 기업",cov.companies,"개"],["GICS 섹터",cov.sectors,"개"]].map(([l,v,u])=><div key={l}><span>{l}</span><strong>{num(v)}<small>{u}</small></strong></div>)}</div>
  </section>
  <section id="tb-questions" className="tb-section"><div className="tb-section-label">CASE 3에서 확장한 질문</div><h2>기업 텍스트에서 시작해 거시 인식과 연결합니다</h2>
   <div className="tb-stages">{stages.map(([step,title,text])=><div key={step}><div className="tb-stage-number">{step}</div><Prose id={`tb:stage:${step}`}>{`### ${title}\n\n${text}`}</Prose></div>)}</div>
   <div className="tb-two"><div className="tb-source-block"><div className="tb-pill">TOP-DOWN</div><h3>FOMC 의사록</h3><Prose id="tb:td">정례회의 연 8회. 물가·고용·성장·투자·금융여건에 대한 종합적인 평가를 담습니다. 실제 공개일부터 투자 정보로 사용합니다.</Prose></div><div className="tb-source-block"><div className="tb-pill">BOTTOM-UP</div><h3>기업 실적 보도자료</h3><Prose id="tb:bu">SEC 8-K의 실적 첨부문서에서 실적 설명과 가이던스를 추출합니다. 기업별 점수를 만든 뒤 전체 표본과 섹터별 차이를 비교합니다.</Prose></div></div>
  </section>
  <section id="tb-data" className="tb-section"><div className="tb-section-label">ACTUAL COVERAGE</div><h2>목표 모집단과 실제 확보 표본을 구분합니다</h2><Prose id="tb:coverage">목표는 S&P 500과 GICS 11개 섹터입니다. 아래는 실제 확보한 기업·문서 수입니다. 현재 구성종목에 기반한 표본에는 생존편향이 있으며, 섹터당 기업 수가 적으면 섹터 전체로 일반화하기 어렵습니다.</Prose>
   {sectors.length?<div className="tb-chart-card"><EvidenceChart id="tb-sector-documents" queryId="sector_coverage" title="섹터별 확보한 실적 자료" rows={sectors} sourceRows={sectors} height={380} spec={{type:"horizontalBar",x:"label",y:"documents",valueDecimals:0,colors:["#157D7D"]}}/></div>:<Empty>기업 자료 수집 결과를 기다리고 있습니다.</Empty>}
   <div className="tb-module-list" data-reviewed-rows>{(res.modules||[]).filter(m=>m.id!=="finbert").map(m=><div key={m.id}><strong>{m.question||m.id}</strong><span>{m.status?.startsWith("executed")?"탐색 분석 실행":m.status?.startsWith("unavailable")?"표본 부족":"후속 검증"}</span></div>)}</div>
  </section>
  <section id="tb-macro" className="tb-section"><div className="tb-section-label">MACRO TOPICS</div><h2>같은 의사록도 주제에 따라 다른 모습을 보입니다</h2><Prose id="tb:macro">주제별 어조는 해당 문장의 긍정·부정 단어 차이입니다. 점수의 단위는 전체 단어 대비 비율(%)이며, 어조는 긍정 비율에서 부정 비율을 뺀 값입니다. 물가 관련 어조가 낮다고 물가가 하락했다는 뜻은 아닙니다. 경제 상태의 방향과 기업 손익 영향은 별도로 확인해야 합니다.</Prose>
   {rows("fomc_tone").length>0&&<div className="tb-chart-card"><EvidenceChart id="tb-fomc-trend" queryId="fomc_tone" title="FOMC 전체 어조와 불확실성" rows={rows("fomc_tone")} sourceRows={rows("fomc_tone")} height={320} spec={{type:"line",x:"date",y:"tone",fields:["tone","uncertainty"],legend:{labels:{tone:"전체 어조",uncertainty:"불확실성"}},valueDecimals:2,stackable:false,colors:["#157D7D","#A67836"]}}/></div>}
   <div className="tb-controls"><label>거시 주제<select value={topic} onChange={e=>setTopic(e.target.value)}>{topics.map(t=><option key={t}>{t}</option>)}</select></label><label>지표<select value={metric} onChange={e=>setMetric(e.target.value)}><option value="tone">주제별 어조</option><option value="topicShare">문장 비중</option></select></label></div>
   {topicRows.length?<div className="tb-chart-card"><EvidenceChart key={metric} id="tb-topic-trend" queryId="fomc_topics" title={`${topic} · ${metric==="tone"?"어조 점수":"문장 비중(%)"}`} rows={topicRows} sourceRows={topicRows} height={300} spec={{type:"line",x:"date",y:metric,valueDecimals:3,stackable:false,colors:["#157D7D"]}}/></div>:<Empty>해당 주제의 관측값이 없습니다.</Empty>}
   {metric==="topicShare"&&<Prose id="tb:share-unit">문장 비중은 전체 문장 중 해당 주제를 언급한 문장의 비율을 백분율로 표시합니다. 같은 문장이 여러 주제에 포함될 수 있으므로 주제별 비중의 합이 100%일 필요는 없습니다.</Prose>}
  </section>
  <section id="tb-models" className="tb-section"><div className="tb-section-label">OUT-OF-SAMPLE</div><h2>결합 모델의 가치는 미래 구간에서 판단합니다</h2><Prose id="tb:models">탑다운 단독, 바텀업 단독, 결합 모델을 같은 정보 마감일과 평가 구간에서 비교합니다. IC는 예측 순위와 이후 수익률 순위의 상관입니다.</Prose>
   {models.length?<DataComponent id="tb-model-table" queryId="models" title="모델별 표본 외 성과" kind="table" sourceRows={models}><div className="tb-table-wrap"><table><thead><tr><th>모델</th><th>관측 수</th><th>평가 분기</th><th>평균 IC</th><th>예측 오차</th></tr></thead><tbody>{models.map((m,i)=><tr key={i}><td>{modelNames[m.model]||m.label||m.model}</td><td>{num(m.n_oos)}</td><td>{num(m.n_periods)}</td><td>{fmt(m.mean_ic)}</td><td>{fmt(m.rmse,4)}</td></tr>)}</tbody></table></div></DataComponent>:<Empty>기업 텍스트와 수익률이 연결된 뒤 모델 성과를 표시합니다.</Empty>}
   {models.some(m=>m.mean_ic!=null)&&<div className="tb-chart-card"><EvidenceChart id="tb-model-ic" queryId="models" title="모델별 평균 순위 예측력" rows={models.map(m=>({...m,label:modelNames[m.model]||m.model}))} sourceRows={models} height={270} spec={{type:"bar",x:"label",y:"mean_ic",valueDecimals:3,colors:["#157D7D"]}}/></div>}
   {rows("portfolio_growth").length>0&&<div className="tb-chart-card"><EvidenceChart id="tb-portfolio-growth" queryId="portfolio_growth" title="비용 차감 후 롱숏 누적 가치 · 시작값 1" rows={rows("portfolio_growth")} sourceRows={rows("portfolio_growth")} height={320} spec={{type:"line",x:"date",y:"combined",fields:["baseline","bottom_up","top_down","combined"],legend:{labels:modelNames},stackable:false,valueDecimals:2,colors:["#8B919A","#4477AA","#B18545","#157D7D"]}}/><Prose id="tb:portfolio-note">예측 상위 1/3을 롱 100%, 하위 1/3을 숏 100%로 편입합니다. 거래대금당 10bp를 차감했으며, 대차료·자금조달·시장충격은 포함하지 않았습니다. 이 선택 표본의 성과를 시장 전체에 일반화할 수 없습니다.</Prose></div>}
   <div className="tb-controls"><label>아래 유효성·주제·괴리 분석의 범위<select value={sector} onChange={e=>setSector(e.target.value)}><option value="All">전체 표본</option>{sectors.map(s=><option key={s.sector} value={s.sector}>{s.label}</option>)}</select></label></div>
   {sector!=="All"&&<Prose id="tb:sector-caution">섹터별 소수 기업을 비교하는 탐색 결과입니다. 같은 통합 모델의 예측을 해당 섹터에서 평가했으며, 섹터별 모델을 따로 학습한 결과는 아닙니다. 한두 기업의 변화가 순위상관에 크게 영향을 줄 수 있습니다.</Prose>}
   {sectorModels.length>0&&<DataComponent id="tb-sector-models" queryId="models_by_sector" title="선택한 섹터의 모델 성과" kind="table" sourceRows={sectorModels}><div className="tb-table-wrap"><table><thead><tr><th>모델</th><th>관측 수</th><th>평가 분기</th><th>평균 IC</th><th>예측 오차</th></tr></thead><tbody>{sectorModels.map(m=><tr key={m.model}><td>{modelNames[m.model]||m.model}</td><td>{num(m.n_oos)}</td><td>{num(m.n_periods)}</td><td>{fmt(m.mean_ic)}</td><td>{fmt(m.rmse,4)}</td></tr>)}</tbody></table></div></DataComponent>}
   {valid.length?<DataComponent id="tb-validity" queryId="signal_validity" title="선택한 범위의 신호 유효성" kind="table" sourceRows={valid}><div className="tb-table-wrap"><table><thead><tr><th>기업 텍스트 신호</th><th>평균 IC</th><th>HAC t값</th><th>관측 분기</th><th>중앙 기업 수</th></tr></thead><tbody>{valid.map((r,i)=><tr key={i}><td>{signalNames[r.signal]||r.signal}</td><td>{fmt(r.mean_ic)}</td><td>{fmt(r.hac_t,2)}</td><td>{num(r.n_periods)}</td><td>{num(r.median_firms_per_period)}</td></tr>)}</tbody></table></div></DataComponent>:<Empty>선택한 범위의 검증 결과가 아직 없거나 표본 기준을 충족하지 못했습니다.</Empty>}
   <h3>어떤 주제가 예측에 추가로 도움이 되었을까요?</h3><Prose id="tb:ablation-note">같은 학습·평가 구간에서 결합 모델의 주제별 변수를 하나씩 제외합니다. 아래 오차 증가율이 양수이면 해당 주제를 뺐을 때 예측 오차가 커졌다는 뜻입니다. 전체 어조는 유지하므로 주제별 변수의 추가 기여를 측정하며, 인과적 영향력이나 경제적 민감도를 뜻하지 않습니다.</Prose>
   {ablation.length>0&&<DataComponent id="tb-ablation" queryId="topic_ablation" title="주제 제외 전후의 예측력 비교" kind="table" sourceRows={ablation}><div className="tb-table-wrap"><table><thead><tr><th>제외한 주제</th><th>관측 수</th><th>평가 분기</th><th>오차 증가율</th><th>IC 감소폭</th></tr></thead><tbody>{ablation.map(r=><tr key={r.topic}><td>{snapshot.research?.topics?.[r.topic]||r.topic}</td><td>{num(r.n_oos)}</td><td>{num(r.n_periods)}</td><td>{fmt(r.rmse_increase_pct,2)}%</td><td>{fmt(r.ic_loss)}</td></tr>)}</tbody></table></div></DataComponent>}
   <h3>괴리가 줄었다는 사실만으로 승자를 정할 수는 없습니다</h3><div className="tb-three">{[["기업 쪽으로 조정","연준 인식이 기존 기업 인식 방향으로 움직이는가?"],["연준 쪽으로 조정","기업 인식이 기존 연준 인식 방향으로 움직이는가?"],["동시 조정·괴리 지속","양측이 신규 정보를 반영하거나 구조적 차이를 유지하는가?"]].map(([title,text],i)=><div key={title}><Prose id={`tb:gap:${i}`}>{`### ${title}\n\n${text}`}</Prose></div>)}</div><Prose id="tb:gap-note">아래는 과거 자료로 표준화한 LM 어조 격차의 사후 변화입니다. 표준화한 어조 차이의 절댓값이 1 이상인 사례를 골라 다음 분기에 25% 이상 축소되었는지 확인합니다. 경제에 대한 판단의 정확성을 의미하지 않으며, 사후 수렴 유형은 과거 매매 신호에 넣지 않습니다.</Prose>
   <div className="tb-controls"><label>괴리 분석 주제<select value={gapTopic} onChange={e=>setGapTopic(e.target.value)}><option value="overall">전체 어조</option>{Object.entries(snapshot.research?.topics||{}).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label></div>
   {gap.length?<div className="tb-chart-card"><EvidenceChart id="tb-gap" queryId="gap_summary" title="다음 분기 어조 격차의 변화" rows={gap} sourceRows={gap} height={280} spec={{type:"horizontalBar",x:"label",y:"count",valueDecimals:0,colors:["#157D7D"]}}/></div>:<Empty>해당 범위에서 사전 격차 기준을 충족하는 사례가 없습니다.</Empty>}
   {leads.length>0&&<DataComponent id="tb-lead-lag" queryId="lead_lag" title="다른 출처의 어조가 다음 어조 예측에 도움이 되는가?" kind="table" sourceRows={leads}><div className="tb-table-wrap"><table><thead><tr><th>추가한 정보와 예측 대상</th><th>평가 횟수</th><th>오차 감소율</th></tr></thead><tbody>{leads.map((r,i)=><tr key={i}><td>{r.direction==="bottom_up_to_top_down"?"기업 어조 추가: 다음 FOMC 어조":"FOMC 어조 추가: 다음 기업 어조"}</td><td>{num(r.n_oos)}</td><td>{fmt(r.improvement_pct,2)}%</td></tr>)}</tbody></table></div><Prose id="tb:lead-definition">자기 자신의 직전 어조만 사용하는 모형과, 다른 출처의 어조를 추가한 모형을 비교합니다. 오차 감소율이 음수이면 정보를 추가했을 때 예측이 나빠졌다는 뜻입니다.</Prose></DataComponent>}
  </section>
  <section id="tb-methods" className="tb-section"><div className="tb-section-label">HOW TO READ THIS STUDY</div><h2>텍스트 점수와 투자 성과 사이의 단계를 확인합니다</h2>
   <div className="tb-two"><div><h3>LM 금융 사전</h3><Prose id="tb:lm">금융 문서에 맞춘 단어 목록으로 긍정·부정·불확실성 비율을 계산합니다. 전체 문서와 미래 전망 문장, 주제별 문장을 각각 측정합니다.</Prose></div><div><h3>FinBERT 비교 트랙</h3><Prose id="tb:fb">문맥을 반영해 문장별 긍정·부정·중립 확률을 산출합니다. 중립 확률은 불확실성 점수가 아닙니다. 실제 실행 범위는 결과 및 README에 기록합니다.</Prose></div></div>
   {fb.status==="executed"&&<Prose id="tb:fb-result">{`같은 문장으로 LM·FinBERT를 비교한 표본은 ${num(fb.documents)}개 문서·${num(fb.sentences)}개 문장입니다. 두 점수의 순위상관은 ${fmt(fb.lm_finbert_matched_spearman)}입니다. 이는 방법 간 일치도이며 분류 정확도나 투자 수익률 검증은 아닙니다.`}</Prose>}
   {rows("finbert_summary").length>0&&<DataComponent id="tb-finbert-sources" queryId="finbert_summary" title="출처별 문서 점수 일치도" kind="table" sourceRows={rows("finbert_summary")}><div className="tb-table-wrap"><table><thead><tr><th>출처</th><th>문서 수</th><th>LM·FinBERT 순위상관</th></tr></thead><tbody>{rows("finbert_summary").map(r=><tr key={r.source}><td>{r.source.startsWith("SEC")?"기업 실적 보도자료":"FOMC 의사록"}</td><td>{num(r.documents)}</td><td>{fmt(r.matched_spearman)}</td></tr>)}</tbody></table></div></DataComponent>}
   <details className="tb-details"><summary>검증 기준과 현재 한계</summary><Prose id="tb:limits">{[
    '- 현재 구성종목과 현재 섹터 분류를 과거에 적용한 선택 표본입니다. 생존편향과 표본 선택의 영향을 받습니다.',
    '- 공개 후 자료만 사용하며 계수·표준화는 과거 학습 구간에서 추정합니다. 분기 말 마지막 거래일 00:00 UTC 이전 공개된 자료를 해당일 종가 편입에 사용합니다.',
    '- FOMC 원문 80건을 수집했어도 분기별 최신 문서를 사용하는 투자 패널의 거시 시점은 최대 40개입니다. 기업 수만큼 독립적인 거시 표본이 늘어나는 것은 아닙니다.',
    '- BHAR의 비교 기준은 광범위한 미국 주식시장 수익률입니다. S&P 500 초과수익이나 팩터 알파와 다릅니다. 예측 오차(RMSE)는 수익률 소수 단위입니다.',
    '- 롱숏은 롱 100%·숏 100%를 가정합니다. 거래비용은 거래대금당 10bp이며 대차료·자금조달·시장충격은 제외합니다.',
    '- 섹터당 소수 기업과 제한된 분기로 수많은 가설을 비교합니다. t값만으로 전략의 유효성을 확정하지 않습니다.',
    '- LM 어조와 규칙 기반 주제 분류는 경제 상태의 방향이나 인과관계를 판별하지 않습니다.',
    '- 전체 FinBERT 수익률 검증, 실적 서프라이즈 통제, 회계 실적 검증은 후속 단계입니다.'
   ].join('\n')}</Prose></details>
   <Prose id="tb:sources">공식 자료: [FOMC 의사록](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) · [SEC EDGAR](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) · [GICS](https://www.spglobal.com/spdji/en/landing/topic/gics/) · [LM 사전](https://sraf.nd.edu/) · [FinBERT](https://huggingface.co/ProsusAI/finbert)</Prose>
  </section><footer className="tb-footer">DFMBA Financial Data Analytics · Case 3 기반 텍스트 투자 연구</footer>
 </article>;
}
