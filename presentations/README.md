# 발표 자료

- `proposal_7min.pptx`: 7분 제안 발표, 9장. 각 장의 발표자 노트에 시간 배분, 한국어 대본과 출처를 포함합니다.
- `results_pilot.pptx`: 실제 수집 자료로 실행한 탐색적 파일럿 결과. 표본 범위, 주제·섹터 분석, 표본 밖 예측과 괴리 분석의 한계를 함께 표시합니다.
- 전체 발표 대본: [`../docs/presentation_script.md`](../docs/presentation_script.md)

제안 발표는 투자 접근법 소개, 분석 자료, 단계별 연구 질문, 텍스트 점수화, 검증 설계, 투자 활용 순서로 구성합니다. 표와 도식, 텍스트는 PowerPoint에서 편집할 수 있습니다. 목표 분석과 실제 결과를 혼동하지 않도록 제안 발표의 내용은 연구 계획으로 표시합니다.

## PPT 재생성

파일을 열어 발표하는 데에는 별도 Python 환경이 필요하지 않습니다. 소스에서 재생성할 때만 Windows의 Microsoft PowerPoint와 `pywin32`가 필요합니다. 분석 파이프라인은 PowerPoint에 의존하지 않습니다.

```powershell
python scripts/build_slides.py --proposal
python scripts/build_slides.py --results reports/results.json
```

출력은 이 폴더에 저장하며, 슬라이드 렌더링 이미지와 레이아웃 검사 기록은 Git에 포함하지 않는 `.build/slides/`에 저장합니다.

결과 발표는 `reports/results.json`의 실제 수치에서 생성합니다. 분석을 다시 실행한 뒤 결과 PPT도 다시 생성해야 HTML과 PPT가 같은 결과를 보여줍니다.

기본 서체는 맑은 고딕이며 화면 비율은 16:9입니다. 다른 운영체제에서 서체를 대체하면 줄바꿈이 달라질 수 있습니다.
