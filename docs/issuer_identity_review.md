# 현재 티커와 연구기간 기업의 연결 검토

검토일: 2026-10-31. 연구기간은 2016–2025년이고 구성종목 스냅샷은 2026-10-31에 고정했습니다. 최근의 티커를 과거 CRSP 티커 문자열에 그대로 연결하면 동명이거나 과거에 같은 문자를 사용한 다른 기업이 섞일 수 있습니다. 아래는 공식 발표로 확인한 변경 사례입니다. 실제 연결 결과는 시장 자료의 기업명·주식 클래스·관측 기간 검토를 거쳐 반영하며, 이 표 자체가 가격 자료 매칭의 완료를 뜻하지는 않습니다.

| 현재 티커 | 공식 자료에서 확인한 사건 | 2016–2025년 연결 판단 |
|---|---|---|
| ECHO | 2026-06-24 SATS에서 ECHO로 티커 변경 | 같은 발행사의 SATS 이력과 대조. 과거의 다른 ECHO 기업과 자동 연결하지 않음 |
| P | Pure Storage가 Everpure로 사명 변경한 뒤, 2026-04-17 PSTG에서 P로 티커 변경. CUSIP 유지 발표 | PSTG 이력과 대조. 과거 P 티커를 사용한 다른 기업의 가격과 연결하지 않음 |
| MRSH | 2026-01-14 MMC에서 MRSH로 변경. 법인명·CUSIP 유지 발표 | MMC 이력과 대조 |
| BNY | 2026-05-21 BK에서 BNY로 변경. 법인명·자본구조·CUSIP 유지 발표 | BK의 보통주 이력과 대조. 연구기간 BNY를 사용한 다른 폐쇄형펀드와 연결하지 않음 |
| SKYD | 2026-10-06 PSKY에서 SKYD로 변경. WBD를 자회사로 편입 | 연구기간 PSKY 이력과 대조. 이전 Paramount 계열의 별도 법인·주식 이력은 자동으로 이어붙이지 않음 |
| VMRK | 2026-08-17 EQR·AVB 합병 완료. AVB 주식을 EQR 주식으로 교환하고 결합기업 이름 변경 | 스냅샷 CIK 906107의 EQR 이력과 대조. 현재 결합기업의 경제적 범위와 과거 EQR의 차이는 남음 |
| FDXF | 2026-06-01 FedEx Freight 분할 완료 및 독립 정규 거래 시작 | 연구기간의 독립 주가 없음. 모기업 FDX 가격으로 대체하지 않음 |
| HONA | 2026-06-29 Honeywell Aerospace 분할 완료 및 독립 거래 시작 | 연구기간의 독립 주가 없음. HON 가격으로 대체하지 않음 |
| VYLR | 2026-10-01 Corteva의 Seed Business 분할. 신규 CIK 2128626 | 연구기간의 독립 주가 없음. 회계상 과거 재무제표 승계와 실제 독립 주식 수익률은 다르므로 CTVA 가격으로 대체하지 않음 |

공식 근거:

- ECHO: [EchoStar 티커 변경 발표](https://ir.echostar.com/news-releases/news-release-details/echostar-changing-stocker-ticker-sats-echo-marking-companys-next).
- P: [Everpure 티커 변경 발표](https://www.everpuredata.com/company/newsroom/press-releases/everpure-to-change-ticker-symbol.html), [동일 CIK의 사명 변경 공시](https://www.sec.gov/Archives/edgar/data/1474432/000147443226000011/pstg-20260223.htm).
- MRSH: [Marsh 티커 변경 발표](https://www.marsh.com/en/corp/about/news/marsh-mclennan-to-change-nyse-symbol-to-mrsh.html).
- BNY: [Bank of New York Mellon 티커 변경 발표](https://www.bny.com/corporate/global/en/about-us/newsroom/press-release/bny-announces-planned-change-of-stock-ticker-symbol-to-bny-130465.html).
- SKYD: [Skydance 거래소·티커 변경 및 합병 완료 8-K](https://www.sec.gov/Archives/edgar/data/2041610/000110465926113913/tm2626659d7_8k.htm).
- VMRK: [주식 교환·존속 구조 발표](https://www.sec.gov/Archives/edgar/data/915912/000110465926094930/tm2622947d1_ex99-1.htm), [합병 완료 발표](https://www.sec.gov/Archives/edgar/data/915912/000110465926097833/tm2623381d1_ex99-1.htm).
- FDXF: [FedEx의 분할 완료 발표](https://investors.fedex.com/news-and-events/investor-news/investor-news-details/2026/FedEx-Completes-Spin-Off-of-FedEx-Freight/default.aspx).
- HONA: [Honeywell의 분할 완료 발표](https://www.honeywell.com/us/en/news/press-releases/2026/06/honeywell-technologies-launches-independent-pure-play-automation-company-following-honeywell-aerospace-spin-off).
- VYLR: [Vylor의 분할·거래 개시 공시](https://www.sec.gov/Archives/edgar/data/2128626/000119312526402928/ck0002128626-20260924.htm), [회계상 승계 설명](https://www.sec.gov/Archives/edgar/data/1755672/000175567226000028/ctva-20261001.htm).

회계상 승계, 법적 존속, 주식의 수익률 연속성은 서로 다른 기준입니다. 기업명이 비슷하다는 이유로 합병 전 기업 여러 개의 텍스트·주가를 합치지 않습니다. 사유를 확인할 수 없는 매칭은 제외 또는 격리하고 그 수를 커버리지에 남깁니다. 과거의 지수 구성종목·GICS 복원은 이 연결 검토와 별도의 후속 과제입니다.

## 과거 공시 식별자 복구

가격 식별과 별도로, 동일 발행사의 법인 재편으로 과거 SEC CIK가 달라진 경우를 검토합니다. 적용한 CIK 목록·경계일·근거는 [연구 설정](../configs/research.json)에 있고, 첨부문서별 예외는 [원문 복구 설정](../configs/source_recovery.json)에 있습니다. 다음 두 사례는 공식 완료 공시로 자산 승계와 1:1 교환을 확인했습니다.

| 기업 | 확인한 연속성과 수집 경계 | 공식 근거 |
|---|---|---|
| STERIS | 2019-03-28 영국에서 아일랜드 지주회사로 재편, 기존 주주에게 1:1 교환. 이전 CIK 1624899의 자료는 2019-03-27까지, 이후 CIK 1757898 사용 | [완료 8-K](https://www.sec.gov/Archives/edgar/data/1757898/000119312519089164/d725181d8k.htm), [이전 CIK의 실적 발표 예시](https://www.sec.gov/Archives/edgar/data/1624899/000119312518156709/d560774dex991.htm) |
| Texas Pacific Land | 2021-01-11 신탁의 자산·직원·부채를 법인으로 이전하고 지분을 1:1 교환. 이전 CIK 97517의 자료는 2021-01-10까지, 이후 CIK 1811074 사용 | [법인 완료 8-K](https://www.sec.gov/Archives/edgar/data/1811074/000121390021001303/ea133016-8k_texaspacific.htm), [이전 신탁의 완료 공시](https://www.sec.gov/Archives/edgar/data/97517/000121390021001308/ea133013-8k_texaspacific.htm) |

인수로 새로 편입된 다른 기업의 과거 문서를 기존 기업의 실적 자료로 자동 합치지는 않습니다. 이 복구는 동일 기업의 자료 연속성을 보완하며, 과거 S&P 500 구성 여부를 복원하는 작업은 아닙니다.
