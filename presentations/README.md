# 발표 자료

- [proposal_7min.pptx](proposal_7min.pptx): 현재 제안 발표, **6장·7분**. 사용자가 제시한 참고자료의 갈색·차콜·회색 디자인을 반영했습니다. 출처 자료, 네 가지 가설, 텍스트 점수화, 한 장의 4단계 도형, 검증과 투자 활용 순서로 구성합니다.
- [proposal_7min.pdf](proposal_7min.pdf): 현재 제안 발표의 PDF 내보내기, **6페이지**. PPT와 페이지별 텍스트가 일치함을 확인했습니다.
- [results_pilot.pptx](results_pilot.pptx): 33개 기업의 탐색적 파일럿 결과, 9장. 초기 분석의 기록으로 보존합니다.
- [results_full.pptx](results_full.pptx): 최종 전수 대상 결과, 9장·약 7분 10초. 현재 구성종목 500개 발행사 전체를 수집 대상으로 삼아 497개 기업의 실적발표자료 19,613건과 FOMC 의사록 81건을 분석했습니다. 분기 패널 497개 기업과 완결 수익률의 표본 밖 평가 495개 기업을 구분합니다.
- 현재 제안 발표 대본: [../docs/presentation_script_v2.md](../docs/presentation_script_v2.md). 6장에 420초를 배분했습니다. PPT의 발표자 노트에도 대본과 출처가 있습니다.
- 최초 9장 대본: [../docs/presentation_script.md](../docs/presentation_script.md). 이전 설계의 기록이며 현재 6장 PPT에 대응하는 대본은 아닙니다. 최초 PPT는 Git 이력에서 확인할 수 있습니다.

현재 제안 2장의 이미지는 연준과 JPMorganChase 공식 사이트가 제공하는 **실제 PDF 원문 발췌**입니다. 브라우저의 현재 URL을 검증할 수 없어 웹페이지 UI 화면 캡처가 중단됐기 때문에, 공식 원문 이미지와 자료 제공 사이트 하이퍼링크로 구성했습니다. 웹사이트 화면 캡처로 표시하지 않습니다. 출처와 이미지 해시는 [assets/proposal/sources.json](assets/proposal/sources.json)에 있습니다.

최종 결과 발표의 예측 성과는 26분기, 비용 후 포트폴리오 성과는 공통 24분기입니다. 현재 구성종목의 과거 자료를 분석한 것이며, 과거 각 시점의 S&P 500 편입·편출을 복원한 표본은 아닙니다. 전수 판본에는 표본 확대와 원문 교정이 함께 반영되어 파일럿과의 차이를 표본 확대만의 효과로 해석할 수 없습니다.

표·도식·차트·텍스트는 PowerPoint에서 편집할 수 있습니다. 기본 서체는 맑은 고딕이며 화면 비율은 16:9입니다. 다른 운영체제에서 서체가 대체되면 줄바꿈이 달라질 수 있습니다.

## PPT 재생성

발표 파일을 여는 데에는 Python 환경이 필요하지 않습니다. 소스에서 재생성할 때만 Windows의 Microsoft PowerPoint와 `pywin32`가 필요합니다. 분석 파이프라인은 PowerPoint에 의존하지 않습니다.

저장소 루트에서 실행합니다.

```powershell
# 최초 9장 설계의 검토용 후보: .build/slides/proposal_legacy/candidate.pptx
python scripts/build_slides.py --proposal
# 6장 설계의 검토용 후보: .build/slides/proposal_7min_v2/candidate.pptx
python scripts/build_proposal_v2.py
# 전수 결과 PPT 갱신
python scripts/build_slides.py --full-results reports/results.json
```

두 제안 생성기는 PPT 후보·대본·검사 기록을 `.build`에만 저장합니다. 현재 PPT·PDF와 공개 대본·manifest는 덮어쓰지 않습니다. 후보를 현재 발표와 비교해 직접 편집한 내용을 유지한 뒤, 검토를 마친 파일만 수동으로 `presentations/proposal_7min.pptx`에 반영합니다. 변경 후에는 같은 PPT에서 PDF를 다시 내보내고, [proposal_revision.json](proposal_revision.json)의 파일 경로·장수·시간·PPT/PDF SHA-256을 함께 갱신합니다.

최종 전수 발표는 동결된 [reports/results.json](../reports/results.json)과 [reports/finbert_method_comparison.json](../reports/finbert_method_comparison.json)의 실제 수치에서 생성했습니다. 분석을 다시 실행하면 HTML과 PPT를 함께 갱신해야 같은 결과를 보여줍니다. `--full-results`는 최종 전수 범위와 기업·주식 클래스별 분모가 명시된 결과만 허용하며 중간 수집 결과로는 생성하지 않습니다.

`--results` 옵션은 입력 JSON의 `meta.scope`에 따라 파일럿·전수 출력 이름을 선택합니다. 현재의 최종 `reports/results.json`으로 과거 파일럿을 재생성하지 않습니다. 전수 결과 생성은 기존 `proposal_7min.pptx`와 `results_pilot.pptx`를 덮어쓰지 않습니다.

## 검증

현재 제안은 PPT 6장·발표자 노트 6개와 PDF 6페이지를 확인했습니다. PDF의 각 페이지에 해당 PPT 텍스트가 모두 포함되며 전체 페이지를 렌더링해 확인했습니다. 현재 파일을 재생성하지 않고 보존했으며, `scripts/verify_outputs.py`는 제안 manifest와 PPT/PDF 해시를 대조합니다.

최종 전수 발표는 Microsoft PowerPoint에서 9장을 모두 렌더링해 시각적으로 확인했습니다. 텍스트 넘침, 슬라이드 비율, 표와 제목의 배치를 검사했고 발표자 노트 9개와 편집 가능한 차트 3개를 확인했습니다. 렌더링 이미지·검사 기록·입력 파일 해시는 Git에서 제외되는 `.build/slides/results_full/`에 저장합니다.
