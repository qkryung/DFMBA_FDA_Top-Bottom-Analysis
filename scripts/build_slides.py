"""Build editable Korean decks with native Microsoft PowerPoint on Windows.

Usage: python scripts/build_slides.py --proposal
       python scripts/build_slides.py --results reports/results.json
       python scripts/build_slides.py --full-results reports/results.json

PowerPoint and pywin32 are optional presentation-build dependencies, not analysis
dependencies. The checked-in PPTX files can be read on other operating systems.
All diagrams/tables/text are editable; preview PNGs remain in .build/slides.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    import win32com.client
except ImportError:
    win32com = None

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "presentations"
BUILD = ROOT / ".build" / "slides"
FONT = "맑은 고딕"
W, H = 960, 540
C = {"navy": "142B45", "teal": "007F80", "text": "23374C", "muted": "657588",
     "white": "FFFFFF", "pale": "EEF5F6", "line": "DAE3E9", "amber": "A76C23"}
SOURCES = {
    "fomc": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "gics": "https://www.spglobal.com/spdji/en/landing/topic/gics/",
    "sec": "https://www.sec.gov/files/form8-k.pdf",
    "lm": "https://sraf.nd.edu/loughranmcdonald-master-dictionary/",
    "finbert": "https://huggingface.co/ProsusAI/finbert",
}


def rgb(hex_value):
    v = C.get(hex_value, hex_value)
    return int(v[0:2], 16) + int(v[2:4], 16) * 256 + int(v[4:6], 16) * 65536


class Deck:
    def __init__(self, stem):
        if win32com is None:
            raise RuntimeError("PPT regeneration requires Windows, Microsoft PowerPoint, and pywin32. The supplied PPTX files need no Python environment.")
        OUT.mkdir(exist_ok=True)
        BUILD.mkdir(parents=True, exist_ok=True)
        self.stem = stem
        self.app = win32com.client.DispatchEx("PowerPoint.Application")
        self.initial_count = self.app.Presentations.Count
        self.p = self.app.Presentations.Add(stem != "proposal_7min")
        if stem != "proposal_7min" and self.initial_count == 0:
            self.app.WindowState = 2
        self.p.PageSetup.SlideWidth, self.p.PageSetup.SlideHeight = W, H
        self.scripts = []
        self.slides = []

    def text(self, s, text, x, y, w, h, size=24, color="text", bold=False,
             align=1, fill=None):
        sh = s.Shapes.AddTextbox(1, x, y, w, h)
        if fill:
            sh.Fill.Visible = -1
            sh.Fill.ForeColor.RGB = rgb(fill)
        else:
            sh.Fill.Visible = 0
        sh.Line.Visible = 0
        tf = sh.TextFrame
        tf.MarginLeft = tf.MarginRight = tf.MarginTop = tf.MarginBottom = 0
        tf.WordWrap = -1
        tf.AutoSize = 0
        tf.TextRange.Text = text
        tr = tf.TextRange
        tr.Font.Name = FONT
        tr.Font.NameFarEast = FONT
        tr.Font.Size = size
        tr.Font.Bold = -1 if bold else 0
        tr.Font.Color.RGB = rgb(color)
        tr.ParagraphFormat.Alignment = align
        tr.ParagraphFormat.SpaceAfter = 6
        tr.ParagraphFormat.SpaceBefore = 0
        # PowerPoint can normalize a fresh textbox to its empty text height.
        # Set the requested geometry after text/font changes for editable fit.
        sh.Left, sh.Top, sh.Width, sh.Height = x, y, w, h
        return sh

    def line(self, s, x1, y1, x2, y2, color="line", width=1.2, arrow=False):
        sh = s.Shapes.AddLine(x1, y1, x2, y2)
        sh.Line.ForeColor.RGB = rgb(color)
        sh.Line.Weight = width
        if arrow:
            sh.Line.EndArrowheadStyle = 3
        return sh

    def slide(self, title, notes, seconds, sources=(), subtitle=None, dark=False):
        s = self.p.Slides.Add(self.p.Slides.Count + 1, 12)
        s.FollowMasterBackground = 0
        s.Background.Fill.ForeColor.RGB = rgb("navy" if dark else "white")
        if title:
            self.text(s, title, 54, 41, 855, 64, 34, "white" if dark else "navy", True)
        if subtitle:
            self.text(s, subtitle, 56, 110, 845, 42, 18, "muted")
        n = s.SlideIndex
        self.text(s, f"{n:02d}", 866, 505, 42, 20, 12, "white" if dark else "muted", align=3)
        nt = f"권장 발표 시간: {seconds}초\n\n{notes}"
        if sources:
            nt += "\n\n출처 및 확인 자료:\n" + "\n".join(SOURCES.get(v, v) for v in sources)
        try:
            s.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text = nt
        except Exception:
            s.NotesPage.Shapes.AddTextbox(1, 50, 100, 620, 600).TextFrame.TextRange.Text = nt
        self.scripts.append((n, title or "표지", seconds, notes, list(sources)))
        self.slides.append(s)
        return s

    def table(self, s, rows, x, y, w, h, widths=None, size=20, header=True):
        shape = s.Shapes.AddTable(len(rows), len(rows[0]), x, y, w, h)
        tb = shape.Table
        if widths:
            for c, wd in enumerate(widths, 1):
                tb.Columns(c).Width = wd
        for ri, row in enumerate(rows, 1):
            for ci, val in enumerate(row, 1):
                cell = tb.Cell(ri, ci)
                sh = cell.Shape
                sh.Fill.ForeColor.RGB = rgb("navy" if header and ri == 1 else "white")
                tf = sh.TextFrame
                tf.MarginLeft, tf.MarginRight = 13, 10
                tf.MarginTop, tf.MarginBottom = 10, 8
                tf.TextRange.Text = str(val)
                tr = tf.TextRange
                tr.Font.Name = tr.Font.NameFarEast = FONT
                tr.Font.Size = size
                tr.Font.Bold = -1 if ri == 1 and header else 0
                tr.Font.Color.RGB = rgb("white" if ri == 1 and header else "text")
                tr.ParagraphFormat.SpaceAfter = 0
                for side in range(1, 5):
                    cell.Borders(side).ForeColor.RGB = rgb("line")
                    cell.Borders(side).Weight = 0.6
        return shape

    def chart(self, s, categories, series, x, y, w, h, percent=False):
        """An editable native horizontal bar chart with its embedded workbook."""
        shape = s.Shapes.AddChart(57, x, y, w, h)
        chart = shape.Chart
        chart.ChartData.Activate()
        workbook = chart.ChartData.Workbook
        sheet = workbook.Worksheets(1)
        sheet.Cells.Clear()
        data = [("구분",) + tuple(v[0] for v in series)]
        data += [(label,) + tuple(float(v[1][i]) for v in series)
                 for i, label in enumerate(categories)]
        sheet.Range(sheet.Cells(1, 1), sheet.Cells(len(data), len(data[0]))).Value = tuple(data)
        chart.SetSourceData(f"='{sheet.Name}'!$A$1:${chr(64+len(data[0]))}${len(data)}")
        chart.HasTitle = False
        chart.ChartArea.Format.Fill.ForeColor.RGB = rgb("white")
        chart.ChartArea.Format.Line.Visible = 0
        chart.ChartArea.Font.Name = FONT
        chart.ChartArea.Font.Size = 17
        chart.HasLegend = len(series) > 1
        if chart.HasLegend:
            chart.Legend.Position = -4107  # bottom
            chart.Legend.Font.Size = 17
        axis = chart.Axes(1)
        axis.TickLabels.Font.Name = FONT
        axis.TickLabels.Font.Size = 17
        axis.TickLabelPosition = -4134  # labels outside plot, even for negative IC
        axis.ReversePlotOrder = True
        value_axis = chart.Axes(2)
        value_axis.TickLabels.Font.Name = FONT
        value_axis.TickLabels.Font.Size = 15
        value_axis.HasMajorGridlines = True
        value_axis.MajorGridlines.Format.Line.ForeColor.RGB = rgb("line")
        if percent:
            value_axis.TickLabels.NumberFormat = "0%"
        # Bar lengths must be measured from zero, including count charts.
        all_values = [float(v) for _, values in series for v in values]
        if min(all_values) >= 0:
            value_axis.MinimumScale = 0
        elif max(all_values) <= 0:
            value_axis.MaximumScale = 0
        for i, (_name, _values) in enumerate(series, 1):
            sr = chart.SeriesCollection(i)
            sr.Format.Fill.ForeColor.RGB = rgb("teal" if i == 1 else "navy")
            sr.Format.Line.Visible = 0
        chart.ChartGroups(1).GapWidth = 65
        workbook.Close(True)
        # Explicit deletion suppresses PowerPoint's automatic single-series title.
        chart.HasTitle = True
        chart.ChartTitle.Delete()
        return shape

    def finish(self, script_path=None):
        path = OUT / f"{self.stem}.pptx"
        self.p.SaveAs(str(path), 24)
        preview = BUILD / self.stem
        preview.mkdir(exist_ok=True)
        qa = {"file": str(path.relative_to(ROOT)), "slide_count": self.p.Slides.Count,
              "total_seconds": sum(v[2] for v in self.scripts), "font": FONT,
              "render_engine": "Microsoft PowerPoint", "text_overflow": []}
        if hasattr(self, "source_sha256"):
            qa["source_sha256"] = self.source_sha256
        if hasattr(self, "finbert_sha256"):
            qa["finbert_sha256"] = self.finbert_sha256
        for slide in self.slides:
            slide.Export(str(preview / f"slide-{slide.SlideIndex:02d}.png"), "PNG", 1600, 900)
            for shape in slide.Shapes:
                if shape.HasTextFrame and shape.TextFrame.HasText:
                    bound = shape.TextFrame.TextRange.BoundHeight
                    usable = shape.Height - shape.TextFrame.MarginTop - shape.TextFrame.MarginBottom
                    if bound > usable + 3:
                        qa["text_overflow"].append({"slide": slide.SlideIndex,
                            "text": shape.TextFrame.TextRange.Text[:100],
                            "bound_height": round(bound, 1), "available_height": round(usable, 1)})
        (preview / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
        if script_path:
            elapsed = 0
            parts = ["# 제안 발표 대본\n\n총 9장, 권장 발표 시간 7분(420초). 슬라이드 발표자 노트에도 같은 대본과 출처가 있습니다.\n"]
            for n, title, sec, notes, sources in self.scripts:
                start, end = elapsed, elapsed + sec
                parts += [f"\n## {n}. {title} ({start//60}:{start%60:02d}–{end//60}:{end%60:02d})\n", notes + "\n"]
                if sources:
                    parts += ["\n출처: " + ", ".join(SOURCES.get(v, v) for v in sources) + "\n"]
                elapsed = end
            script_path.parent.mkdir(exist_ok=True)
            script_path.write_text("\n".join(parts), encoding="utf-8")
        self.p.Close()
        if self.initial_count == 0 and self.app.Presentations.Count == 0:
            self.app.Quit()
        print(json.dumps(qa, ensure_ascii=False, indent=2))
        return path


def proposal():
    d = Deck("proposal_7min")
    s = d.slide(None,
        "저희는 탑다운 분석과 바텀업 분석을 텍스트로 결합하는 연구를 제안합니다. 미국 기업의 실적발표와 FOMC 의사록을 같은 시간축에서 비교해, 각각의 정보가 미래 수익률을 설명하는지, 두 관점을 결합하면 투자 판단이 나아지는지 확인하려고 합니다. 수업의 Case 3에서 다룬 공시 수집과 텍스트 추출이 이 주제의 출발점입니다.",
        25, dark=True)
    d.text(s, "연준의 말과 기업의 말", 55, 118, 850, 70, 44, "white", True)
    d.text(s, "탑다운·바텀업 텍스트 분석의 결합과 투자 활용", 58, 215, 820, 95, 27, "white")
    d.text(s, "미국 S&P 500 기업 및 GICS 섹터 분석", 58, 343, 820, 40, 21, "white")
    d.text(s, "Financial Data Analytics   /   Case 3 기반 연구 제안", 58, 454, 820, 30, 15, "white")

    s = d.slide("서로 다른 관점의 투자 정보",
        "탑다운은 경제 전체에서 출발해 산업과 기업을 살피는 접근이고, 바텀업은 개별 기업의 실적과 경쟁력에서 출발합니다. 탑다운 자료로는 FOMC 의사록을 선택했습니다. 정례회의는 연 8회 열리고 의사록에는 물가, 고용, 성장 등 여러 주제에 대한 평가가 담깁니다. 바텀업 자료는 S&P 500 기업의 실적 보도자료입니다. SEC의 8-K 실적 관련 공시에 첨부된 보도자료와 기업 IR 자료를 사용하며, 실적과 미래 가이던스를 구분합니다. 두 자료가 같은 경제를 다르게 설명하는 순간에 추가 정보가 있을 수 있다는 것이 출발 가설입니다.",
        45, ("fomc", "sec", "gics"))
    d.text(s, "TOP-DOWN", 58, 149, 390, 35, 18, "teal", True)
    d.text(s, "FOMC 의사록", 58, 199, 390, 45, 30, "navy", True)
    d.text(s, "경제 전체의 판단\n물가·고용·성장·투자\n정례회의 연 8회", 58, 271, 385, 147, 24)
    d.line(s, 478, 160, 478, 424)
    d.text(s, "BOTTOM-UP", 525, 149, 380, 35, 18, "teal", True)
    d.text(s, "S&P 500 실적발표", 525, 199, 390, 45, 30, "navy", True)
    d.text(s, "기업 현장의 판단\n수요·원가·실적·가이던스\n분기 실적 보도자료", 525, 271, 385, 147, 24)
    d.text(s, "의사록은 회의일 이후 공개되므로 실제 공개일부터 투자 정보로 사용", 58, 455, 835, 30, 16, "muted")

    s = d.slide("연구의 진행 순서",
        "분석은 네 단계로 진행합니다. 먼저 기업 텍스트만으로 투자 정보가 있는지 검증합니다. 다음으로 FOMC 의사록을 결합했을 때 예측력이 개선되는지 확인합니다. 세 번째로 두 자료를 공통 거시 주제로 나눠 어떤 주제가 어떤 섹터에서 중요한지 분석합니다. 마지막으로 두 관점이 어긋날 때, 기업이 연준보다 먼저 변화를 포착하는지 또는 연준의 인식이 기업으로 전달되는지 살펴봅니다. 모든 단계에서 전체 표본과 섹터별 결과를 함께 비교합니다.",
        40)
    for idx, (a, b) in enumerate([
        ("기업 텍스트의 유효성", "실적·전망 어조와 이후 수익률"),
        ("FOMC 정보의 추가 가치", "기업 단독과 결합 모델 비교"),
        ("주제별·섹터별 차이", "물가·고용·성장·투자·금융여건"),
        ("괴리와 선후행 관계", "어느 정보가 먼저 움직이는가"),
    ]):
        y = 143 + idx * 77
        d.text(s, f"0{idx+1}", 58, y, 66, 43, 28, "teal", True)
        d.text(s, a, 138, y, 390, 42, 25, "navy", True)
        d.text(s, b, 550, y+3, 360, 53, 19)
        if idx < 3:
            d.line(s, 138, y + 56, 899, y + 56)
    d.text(s, "분석 단위: S&P 500 전체와 GICS 섹터", 138, 463, 740, 32, 19, "teal", True)

    s = d.slide("텍스트를 점수로 만드는 방법",
        "점수화는 이해하기 쉬운 사전 방식에서 시작하고 문맥 모델과 비교합니다. Loughran–McDonald 사전으로 긍정, 부정, 불확실성 단어의 비율을 계산합니다. FinBERT는 문장별 긍정, 부정, 중립 확률을 주므로 긍정 확률에서 부정 확률을 뺀 값을 평균합니다. 여기서 FinBERT의 중립은 불확실성과 같은 개념이 아닙니다. 불확실성은 별도 사전 지표로 유지합니다. 실적 서술과 전망 문장을 나눠 점수를 계산하고 반복되는 법적 면책문구가 신호를 지배하지 않도록 처리합니다. FOMC의 긴축 어조와 경기 비관도 구분해야 합니다. 모델이 잘 분류하는지는 사람이 읽은 문장 표본으로 점검합니다.",
        55, ("lm", "finbert"))
    d.table(s, [
        ["방식", "측정 내용", "확인할 한계"],
        ["LM 사전", "긍정·부정·불확실성\n단어 비율", "문맥과 부정 표현"],
        ["FinBERT", "문장별 긍정−부정 확률\n문서 평균", "금융 문맥 적합성\nFOMC 표현 적합성"],
    ], 57, 147, 847, 215, [174, 368, 305], 21)
    d.text(s, "실적 서술과 미래 전망을 구분해 별도 점수화", 58, 390, 835, 38, 24, "teal", True)
    d.text(s, "불확실성 ≠ 중립    /    긴축 어조 ≠ 경기 비관", 58, 451, 835, 35, 20, "muted")

    s = d.slide("1단계: 기업 텍스트 신호의 유효성",
        "기업의 말이 투자 정보로 쓸 만한지부터 확인합니다. 긍정과 부정의 순어조, 불확실성, 미래 전망의 어조를 각각 만들어 실제 공개 이후의 수익률과 연결합니다. 전체 기업의 예측력과 같은 섹터 안에서의 상대 순위를 함께 확인합니다. 평가 지표는 신호와 다음 기간 수익률의 순위상관인 IC, 상위 그룹과 하위 그룹의 수익률 차이, 거래비용 차감 성과입니다. 장기 목표는 2016년부터 2025년까지의 40분기이며, 먼저 확보 가능한 최근 표본으로 파이프라인을 검증합니다. 발표 이후 보유기간을 정하고, 아직 공개되지 않은 자료가 들어가지 않도록 시점을 정렬합니다.",
        45)
    d.text(s, "실적·가이던스", 58, 156, 248, 50, 28, "navy", True)
    d.text(s, "어조 점수", 376, 156, 224, 50, 28, "navy", True)
    d.text(s, "이후 수익률", 686, 156, 225, 50, 28, "navy", True)
    d.line(s, 287, 181, 351, 181, "teal", 2, True)
    d.line(s, 589, 181, 654, 181, "teal", 2, True)
    d.text(s, "긍정·부정\n불확실성\n전망 문장", 58, 230, 250, 125, 23)
    d.text(s, "전체 기업 비교\n동일 섹터 내 비교", 376, 230, 272, 125, 23)
    d.text(s, "순위상관(IC)\n상위−하위 성과\n거래비용 차감", 686, 230, 235, 125, 23)
    d.text(s, "파일럿 검증 후 장기 표본 확장", 58, 402, 830, 39, 25, "teal", True)
    d.text(s, "목표 신호 기간 2016–2025년 40분기, 다음 기간 수익률까지 확보", 58, 454, 845, 32, 18, "muted")

    s = d.slide("2·3단계: 거시 주제와 섹터 민감도",
        "다음으로 FOMC 의사록의 경제 평가를 결합합니다. 한 분기의 FOMC 점수는 모든 기업에 같으므로 이를 그대로 더하거나 빼는 것만으로 기업 순위가 바뀌지는 않습니다. 그래서 거시 국면에 따라 기업 신호의 효용이 달라지는지, 또는 섹터별 거시 민감도가 다른지를 분석합니다. 물가, 고용, 성장과 수요, 투자, 금융여건을 공통 주제로 분류합니다. 예를 들어 임금 상승은 비용 부담이고, 고용 증가는 소비 수요에 도움이 될 수 있습니다. 같은 고용 주제도 비용과 수요의 경로가 다릅니다. 표의 관계는 검증할 가설이며, 실제 영향의 크기와 방향은 전체 및 섹터별 데이터로 추정합니다.",
        60)
    d.table(s, [
        ["거시 주제", "기업에서 확인할 경로", "검증할 차이"],
        ["물가", "판매가격·투입비용·마진", "가격 전가력"],
        ["고용", "임금 부담·채용·소비 수요", "노동집약도"],
        ["성장·투자", "수주·설비투자·매출 전망", "경기 민감도"],
        ["금융여건", "차입비용·고객의 자금 부담", "금리 민감도"],
    ], 57, 138, 847, 280, [175, 410, 262], 21)
    d.text(s, "FOMC 단독·기업 단독·결합 모델의 추가 예측력 비교", 58, 444, 840, 35, 22, "teal", True)
    d.text(s, "경로는 연구 가설이며, 효과의 방향과 크기는 표본에서 검증", 58, 481, 840, 20, 14, "muted")

    s = d.slide("4단계: 괴리는 어느 방향으로 해소되는가",
        "핵심 확장 질문은 두 관점이 다를 때 어느 쪽이 먼저 움직이느냐입니다. 동일한 주제와 방향으로 정렬한 기업의 평가가 강하고 연준의 평가가 약한 상황을 예로 들 수 있습니다. 이후 연준의 평가가 기업 쪽으로 움직이는지, 기업이 연준 쪽으로 움직이는지, 양쪽이 함께 변하는지, 괴리가 계속되는지 구분합니다. 이때 기업 표본 구성이 바뀌어서 평균이 달라지는 효과도 통제합니다. 하지만 정보가 먼저 움직였다는 것과 투자 수익을 얻는다는 것은 별도 문제입니다. 후행 변수의 예측력과 실제 미래 수익률을 각각 검증하고, 전체 기업과 섹터별 선후행 관계를 비교하겠습니다.",
        55)
    d.text(s, "같은 주제에서 기업과 연준의 평가가 다를 때", 58, 130, 850, 40, 24, "teal", True)
    d.table(s, [
        ["이후의 변화", "해석할 정보"],
        ["연준 평가가 기업 쪽으로 조정", "바텀업 정보의 선행 가능성"],
        ["기업 평가가 연준 쪽으로 조정", "탑다운 정보의 선행 가능성"],
        ["양쪽 조정 또는 괴리 지속", "공통 충격·서로 다른 노출 가능성"],
    ], 57, 192, 847, 228, [462, 385], 21)
    d.text(s, "정보의 선행성", 58, 448, 285, 36, 24, "navy", True)
    d.text(s, "투자의 수익성", 520, 448, 338, 36, 24, "navy", True)
    d.text(s, "별도 검증", 368, 452, 140, 31, 19, "teal", True)

    s = d.slide("예측력과 투자 성과의 검증 설계",
        "탑다운이 좋은지 바텀업이 좋은지 미리 결론을 정하지 않습니다. 같은 기간과 같은 통제변수를 사용해 기업 단독, FOMC 단독, 두 정보를 결합한 모델을 비교합니다. FOMC 단독 정보는 시장과 섹터의 시계열 예측으로, 기업 정보는 종목 간 순위 예측으로 평가해 가능한 비교와 불가능한 비교를 구분합니다. 학습은 과거 데이터로만 수행하고 이후 기간으로 검증하는 방식으로 진행합니다. 공개일, 구성종목의 생존편향, 데이터 누락을 점검하고, 섹터와 주제를 많이 나눌수록 표본이 작아진다는 점도 반영합니다. 최종 판단은 거래비용을 뺀 성과와 여러 기간에서의 안정성으로 하겠습니다.",
        55)
    d.table(s, [
        ["비교 모델", "같은 기준으로 평가"],
        ["기업 단독", "전체 기업·섹터 내 미래 수익률"],
        ["FOMC 단독", "시장·섹터의 시계열 예측"],
        ["기업 + FOMC + 민감도", "결합 후 예측력과 비용 차감 성과"],
    ], 57, 141, 847, 240, [350, 497], 21)
    d.text(s, "과거로 학습하고 미래 기간에서 평가", 58, 409, 845, 37, 25, "teal", True)
    d.text(s, "실제 공개일 정렬  /  생존편향·누락 공개  /  작은 표본·다중검정 고려", 58, 466, 845, 32, 17, "muted")

    s = d.slide("검증 결과에 따른 투자 활용",
        "결과의 활용은 확인된 정보의 강점에 맞춥니다. 바텀업 정보가 유효하면 같은 섹터 안에서 종목을 선택하고, 탑다운 정보가 유효하면 거시 민감도를 반영한 섹터 배분에 활용할 수 있습니다. 결합 모델이 안정적으로 더 좋다면 두 정보가 모두 들어간 예측값으로 비중을 결정합니다. 유의한 개선이 없다면 그 결과 자체를 보고하고 괴리를 추가 조사가 필요한 지표로 해석하겠습니다. 최종 산출물은 데이터 수집과 분석 코드, 결과를 탐색할 HTML, 발표용 PPT입니다. GitHub에서 데이터 정의와 재현 방법, 그리고 실제 완료된 분석 범위를 함께 공유하겠습니다.",
        40)
    d.table(s, [
        ["확인한 결과", "활용 방향"],
        ["바텀업 정보의 효용", "동일 섹터 내 종목선정"],
        ["탑다운 정보의 효용", "거시 민감도에 따른 섹터 배분"],
        ["결합 정보의 추가 효용", "결합 예측값에 따른 비중 결정"],
    ], 57, 140, 847, 235, [375, 472], 21)
    d.text(s, "산출물: 재현 가능한 코드 · 결과 HTML · 발표 PPT", 58, 405, 842, 40, 23, "teal", True)
    d.text(s, "유의하지 않은 결과와 데이터 한계도 함께 공개", 58, 462, 840, 30, 20, "muted")
    return d.finish(ROOT / "docs" / "presentation_script.md")


def fmt(value, digits=3, pct=False):
    if value is None:
        return "미산출"
    return f"{value*100:.{digits}f}%" if pct else f"{value:.{digits}f}"


def result_scope(result, require_full=False):
    """Keep issuer, security and estimation universes distinct in every deck."""
    full = result.get("meta", {}).get("scope") == "full_current_constituents"
    if require_full and not full:
        raise ValueError("Full deck requires meta.scope='full_current_constituents'; pilot data cannot be relabelled as full coverage.")
    if full:
        if result.get("meta", {}).get("status") != "exploratory_full_current_universe":
            raise ValueError("Full deck requires final full-universe status; checkpoint results cannot be published as the final presentation.")
        cov = result["coverage"]
        required = ("target_issuers", "target_securities", "attempted_issuers",
                    "document_issuers", "market_matched_issuers",
                    "analysis_issuers", "oos_issuers")
        missing = [key for key in required if cov.get(key) is None]
        if missing:
            raise ValueError("Full deck requires explicit coverage denominators: " + ", ".join(missing))
        if not (0 <= cov["oos_issuers"] <= cov["analysis_issuers"] <= cov["market_matched_issuers"] <= cov["document_issuers"] <= cov["attempted_issuers"] <= cov["target_issuers"] <= cov["target_securities"]):
            raise ValueError("Inconsistent issuer/security coverage denominators.")
    return "full" if full else "pilot"


def results(input_path, require_full=False):
    source_bytes = input_path.read_bytes()
    r = json.loads(source_bytes.decode("utf-8"))
    scope = result_scope(r, require_full)
    full = scope == "full"
    fb_path = input_path.parent / "finbert_method_comparison.json"
    if not fb_path.exists():
        fb_path = ROOT / "reports" / "finbert_method_comparison.json"
    fb_bytes = fb_path.read_bytes() if fb_path.exists() else b""
    fb = json.loads(fb_bytes.decode("utf-8")) if fb_bytes else {}
    fb_done = fb.get("status") == "executed"
    fb_note = (f"별도 방법 비교에서는 {fb['documents']}개 문서에서 추출한 {fb['sentences']:,}개 동일 문장의 LM·FinBERT 점수 일치도를 비교했습니다. 투자성과 비교는 아직 수행하지 않았습니다."
               if fb_done else "FinBERT 비교는 후속 분석입니다.")
    if fb_done and fb.get("truncated_sentences", 0):
        fb_note += f" FinBERT 입력 중 {fb['truncated_sentences']}개 문장은 모델의 길이 제한으로 잘렸습니다."
    cov, meta = r["coverage"], r["meta"]
    evaluated_periods = max((v.get("n_periods", 0) for v in r["models"]), default=0)
    portfolio_period_counts = sorted({v.get("n_portfolio_periods", 0) for v in r["models"]})
    portfolio_period_label = "/".join(str(v) for v in portfolio_period_counts)
    source_urls = tuple(v["url"] for v in r.get("sources", []))
    d = Deck(f"results_{scope}")
    d.source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if fb_bytes:
        d.finbert_sha256 = hashlib.sha256(fb_bytes).hexdigest()
    scope_note = (f"현재 구성종목의 {cov['target_issuers']}개 기업, {cov['target_securities']}개 주식 클래스 전수를 수집 대상으로 삼았습니다. 기업별 대표 주식으로 분석하며, 수집 {cov['document_issuers']}개 기업, 분기 패널 포함 {cov['analysis_issuers']}개 기업, 표본 밖 평가 포함 {cov['oos_issuers']}개 기업입니다. 패널에는 신호와 진입월 가격이 있는 관측치를 포함하며, 표본 밖 평가는 이후 3개월 수익률이 완결된 관측치에 한합니다. 수집 목표 전체와 실제 분석 분모를 구분합니다. 현재 구성종목의 과거 문서를 분석한 것이며 과거 시점의 S&P 500 구성종목을 복원한 결과는 아닙니다."
                  if full else "실제 자료로 실행한 탐색적 파일럿 결과입니다. 현재 구성종목에서 선택한 표본이므로 이 결과를 과거 S&P 500 전체의 결과로 해석할 수는 없습니다.")
    s = d.slide(None,
        f"{scope_note} {cov['tickers']}개 기업, {cov['sectors']}개 섹터의 기업 문서 {cov['firm_documents']:,}건과 FOMC 의사록 {cov['fomc_documents']}건을 처리했습니다. 이번 수익률 분석은 LM 사전 기반입니다. {fb_note}",
        30, source_urls, dark=True)
    d.text(s, "연준의 말과 기업의 말", 55, 103, 850, 75, 44, "white", True)
    d.text(s, "현재 S&P 500 구성종목 전수 대상 분석" if full else "실제 자료로 실행한 탐색적 파일럿", 58, 207, 825, 55, 30, "white")
    if full:
        d.text(s, f"목표 {cov['target_issuers']}기업 · 수집 {cov['document_issuers']}기업 · 패널 {cov['analysis_issuers']}기업", 58, 319, 835, 50, 25, "white", True)
        d.text(s, "현재 구성종목 기준 · LM 사전 분석 · 과거 편입·편출은 미복원", 58, 448, 835, 36, 18, "white")
    else:
        d.text(s, f"{cov['tickers']}개 기업    {cov['sectors']}개 섹터    {cov['formation_periods']}개 형성 분기", 58, 319, 835, 50, 26, "white", True)
        d.text(s, "선택 표본 · LM 사전 분석 · S&P 500 전체로 일반화 불가", 58, 448, 835, 36, 18, "white")

    s = d.slide("실행 데이터와 분석 범위",
        f"기업 문서는 {cov['first_firm_release'][:10]}부터 {cov['last_firm_release'][:10]}까지 공개된 자료입니다. 수익률을 연결한 관측치는 {cov['return_matched']:,}개이며, 실제 수익률로 표본 밖 성과를 평가한 기간은 {evaluated_periods}분기입니다. 예측을 생성했어도 이후 수익률이 없으면 평가에서 제외합니다. 기업마다 문서 확보 수가 다르므로 문서 수와 개별 관측치 수를 함께 공개합니다. GICS는 현재 섹터를 고정해 사용했고 과거 구성종목이나 섹터 이동을 복원하지 않았습니다. " + (f"기업 실적발표자료는 SEC 공시와 검증된 공식 IR에서 확보한 보도자료, 실적 주주서한·공식 업데이트를 포함하며 실적발표 콜 전문은 아닙니다. SEC 공시와 연결되는 날짜만 알려진 IR 대체 원문은 SEC 접수시점과 공식 IR 공개일 다음 날 뉴욕 자정 중 늦은 시점을 가용시점으로 사용합니다. 수집 시도는 {cov['attempted_issuers']}개 기업, 가격 자료가 매칭된 기업은 {cov['market_matched_issuers']}개입니다. 분기 패널 포함 {cov['analysis_issuers']}개 기업과 {cov['panel_rows']:,}개 관측치는 신호와 진입월 가격이 있는 경우이며, 이후 3개월 수익률 완결 여부는 별도 조건입니다. 주식 클래스와 고유 기업 수는 다릅니다. 제외 사유별 세부 수치는 HTML과 결과 JSON에서 확인할 수 있습니다." if full else ""),
        45, source_urls)
    coverage_rows = [
        ["분석 항목", "실행 규모"],
        ["기업 실적 문서", f"{cov['firm_documents']:,}건 / {cov['tickers']}개 기업"],
        ["FOMC 의사록", f"{cov['fomc_documents']:,}건"],
        ["수익률 매칭", f"{cov['return_matched']:,}개 기업·분기 관측치"],
        ["수익률 포함 OOS 평가", f"{evaluated_periods}개 분기"],
    ]
    if full:
        coverage_rows = [
            ["분석 단계", "기업 수와 관측치"],
            ["전체 수집 목표", f"{cov['target_issuers']}기업 / {cov['target_securities']}주식 클래스"],
            ["실적자료 확보 (SEC·공식 IR)", f"{cov['document_issuers']}/{cov['target_issuers']}기업 · {cov['firm_documents']:,}문서"],
            ["분기 패널 포함", f"{cov['analysis_issuers']}/{cov['target_issuers']}기업 · {cov['panel_rows']:,}관측치"],
            ["표본 밖 평가 포함", f"{cov['oos_issuers']}/{cov['target_issuers']}기업 · {evaluated_periods}분기"],
            ["FOMC 의사록", f"{cov['fomc_documents']:,}문서 · {cov['formation_periods']}형성 분기"],
        ]
    d.table(s, coverage_rows, 57, 139, 847, 285, [405, 442], 21 if full else 23)
    d.text(s, f"기업 공개일: {cov['first_firm_release'][:10]} – {cov['last_firm_release'][:10]}", 58, 452, 845, 31, 19, "muted")

    sectors = r["descriptive"]["sector_coverage"]
    sector_ko = {"Communication Services": "커뮤니케이션", "Consumer Discretionary": "경기소비재",
                 "Consumer Staples": "필수소비재", "Energy": "에너지", "Financials": "금융",
                 "Health Care": "헬스케어", "Industrials": "산업재", "Information Technology": "정보기술",
                 "Materials": "소재", "Real Estate": "부동산", "Utilities": "유틸리티"}
    s = d.slide("섹터별 표본 구성",
        ("이 그림은 섹터별로 수집한 기업 문서 수를 보여줍니다. 현재 구성종목 전체를 수집 대상으로 삼아도 상장 시기, 과거 공시의 보존 상태와 수집 성공률에 따라 문서 수에는 차이가 생깁니다. 문서 수가 많은 섹터를 효과가 큰 섹터로 해석하지 않습니다. 수익률 매칭 후 실제 분석에 포함되는 기업 수와 제외 사유도 HTML에서 함께 확인합니다."
         if full else "이 그림은 섹터별로 수집한 기업 문서 수를 보여줍니다. 기업 수를 균형 있게 정해도 과거 공시의 보존 상태와 수집 성공률에 따라 문서 수에는 차이가 생깁니다. 분석의 대표성을 판단할 때 이런 차이를 함께 살펴야 합니다. 현재 표본은 수집과 분석 가능성을 검증하기 위한 표본이며 모든 섹터 내 기업을 대표하지 않습니다."),
        40, source_urls)
    d.chart(s, [sector_ko.get(v["sector"], v["sector"]) for v in sectors],
            [("수집 문서 수", [v["documents"] for v in sectors])], 52, 124, 857, 337)
    d.text(s, "단위: 기업 실적발표자료 건수. 현재 GICS 고정 분류, 확보한 문서 기준" if full else "단위: 실적 문서 건수. 현재 GICS 고정 분류, 선택 표본", 58, 480, 840, 26, 17, "muted")

    topic_names = {"inflation": "물가", "employment": "고용", "growth": "성장·수요",
                   "investment": "투자", "rates": "금융여건"}
    topics = list(topic_names)
    ablation = [v for v in r.get("topic_ablation", []) if v["scope"] == "All" and v.get("rmse_increase_pct") is not None]
    ablation_map = {v["topic"]: v for v in ablation}
    s = d.slide("기업·연준 주제 특성의 추가 예측 기여" if full else "거시 주제 특성의 추가 예측 기여",
        "어떤 거시 주제가 추가 정보인지 보기 위해 결합 모델에서 한 주제의 명시적 특성을 제외하고 다시 학습했습니다. 기업과 FOMC의 해당 주제 어조, 섹터별 거시 상호작용과 해당 주제의 기업·연준 상호작용을 함께 뺍니다. 일반 어조와 일반 상호작용에는 해당 주제의 정보가 일부 남아 있으므로 주제 정보 전체를 제거한 실험은 아닙니다. 그래프는 같은 기업·분기의 표본 밖 관측치에서 주제 제외 후 RMSE가 얼마나 변했는지 보여줍니다. 양수이면 해당 주제 특성을 빼자 예측이 나빠졌다는 뜻이고, 음수이면 제외했을 때 예측이 좋아졌다는 뜻입니다. 이는 기업·FOMC·상호작용의 해당 주제 변수를 함께 제거한 모형 비교이며 FOMC 단독의 기여는 아닙니다. 경제적 인과효과로 해석하지 않습니다. 섹터별 비교는 HTML에서 확인할 수 있습니다.",
        45, source_urls)
    d.text(s, "해당 주제의 명시적 특성을 제외한 뒤 예측오차 변화", 58, 126, 845, 33, 21, "teal", True)
    if ablation:
        topic_order = [t for t in topics if t in ablation_map]
        ch = d.chart(s, [topic_names[t] for t in topic_order], [
            ("주제 제외 후 RMSE 변화", [ablation_map[t]["rmse_increase_pct"] / 100 for t in topic_order]),
        ], 52, 170, 857, 276, percent=True)
        ch.Chart.Axes(2).TickLabels.NumberFormat = "0.0%"
    else:
        d.text(s, "주제별 비교에 필요한 표본 부족으로 미산출", 58, 240, 845, 60, 27, "navy", True)
    d.text(s, "양수: 제외 후 오차 증가    음수: 제외 후 오차 감소", 58, 454, 845, 30, 20, "teal", True)
    d.text(s, "일반 어조는 유지한 모형 비교. 인과효과가 아니며 섹터별 결과는 HTML에서 확인", 58, 489, 845, 20, 14, "muted")

    overall = r["validity"]["overall"]
    signal_labels = {"bu_tone": "전체 순어조", "bu_uncertainty_rate": "불확실성", "bu_forward_tone": "미래 전망 어조",
                     "bu_topic_inflation_tone": "물가 주제 어조", "bu_topic_employment_tone": "고용 주제 어조"}
    selected = [v for key in signal_labels for v in overall if v["signal"] == key]
    if not selected:
        selected = overall[:5]
    s = d.slide("기업 텍스트와 다음 분기 수익률",
        "분기마다 기업 신호와 다음 3개월 시장 대비 수익률의 순위상관을 계산하고, 그 분기별 상관계수를 평균했습니다. IC가 양수이면 신호가 높은 기업의 이후 수익률이 높은 경향이고, 음수이면 반대입니다. 불확실성 지표는 값이 클수록 불확실한 표현이 많다는 의미이므로 어조와 해석이 다릅니다. 표의 t값은 분기 간 상관을 고려한 HAC 추정치이며 여러 섹터와 주제를 동시에 살핀 다중검정을 보정하지 않았습니다. 따라서 탐색 결과로 해석해야 합니다." + (" 이 원점수 유효성 점검은 완결 수익률이 있는 2016년 1분기부터 2025년 3분기까지 39분기의 기술적 분석입니다. 뒤에서 비교하는 학습 모형의 표본 밖 26분기 성과와는 평가 범위가 다릅니다." if full else ""),
        50, source_urls)
    rows = [["기업 신호", "평균 IC", "HAC t", "분기 수"]]
    rows += [[signal_labels.get(v["signal"], v["signal"]), fmt(v.get("mean_ic")), fmt(v.get("hac_t"), 2), str(v["n_periods"])] for v in selected]
    if len(rows) == 1:
        rows.append(["유효성 평가", "미산출", "미산출", "0"])
    d.table(s, rows, 57, 141, 847, 290, [359, 170, 159, 159], 21)
    d.text(s, "원점수 평균 IC · 기술적 점검 39분기 (모델 OOS 26분기와 구분)" if full else "IC = 분기별 횡단면 Spearman 순위상관의 평균", 58, 451, 840, 30, 18, "teal", True)
    d.text(s, "시장 대비 수익률은 미국 주식시장 벤치마크 차감 수익률이며 팩터 알파가 아님", 58, 487, 843, 20, 14, "muted")

    sector_validity = [v for v in r["validity"]["by_sector"] if v["signal"] == "bu_tone" and v.get("mean_ic") is not None]
    s = d.slide("섹터별 기업 어조의 유효성",
        "전체 표본의 평균이 섹터별 차이를 가릴 수 있어 섹터 내부의 기업 순위를 별도로 비교했습니다. 그림은 전체 순어조를 사용한 평균 IC입니다. 섹터 안의 기업 수가 적으면 순위상관은 몇 개 값으로만 움직일 수 있고 추정치도 불안정합니다. 일부 섹터의 수치가 더 크거나 음수라는 이유만으로 매매 방향을 정하지 않습니다. 주제별 세부 수치와 표본 수는 HTML 결과에서 확인할 수 있습니다.",
        45, source_urls)
    if sector_validity:
        d.chart(s, [sector_ko.get(v["scope"], v["scope"]) for v in sector_validity],
                [("평균 IC", [v["mean_ic"] for v in sector_validity])], 52, 124, 857, 337)
    else:
        d.text(s, "섹터별 순위상관의 최소 기업 수 조건 미충족", 58, 205, 840, 80, 28, "navy", True)
    d.text(s, "평균 IC · 원점수 기술적 점검 · 섹터별 표본과 다중검정 검토" if full else "섹터 내 소수 기업의 탐색 결과. 표본 확대와 다중검정 보정 필요", 58, 480, 840, 26, 17, "muted")

    model_order = ["baseline", "bottom_up", "top_down", "combined"]
    models = sorted(r["models"], key=lambda v: model_order.index(v["model"]))
    labels = {"baseline": "통제변수만", "bottom_up": "바텀업", "top_down": "탑다운", "combined": "결합"}
    s = d.slide("정보를 결합했을 때의 표본 밖 성과",
        f"같은 표본과 통제변수를 사용해 기준 모델, 바텀업, 탑다운, 결합 모델을 비교했습니다. 최소 {meta['min_train_quarters']}개의 과거 분기를 학습한 뒤 미래 기간을 예측했습니다. RMSE는 작을수록 예측 오차가 작습니다. 순위상관과 포트폴리오 성과는 다른 기준이므로 함께 보아야 합니다. 롱숏 수익률은 100퍼센트 매수와 100퍼센트 매도 노출을 가정하며, 거래한 금액에 10bp 비용을 적용한 시나리오입니다. 차입비용, 자금조달비용, 시장충격은 포함하지 않았습니다. " + ("기업 수가 늘어도 독립적인 거시 관측 기간이 늘어난 것은 아닙니다. 예측오차와 IC는 26분기, 비용 후 포트폴리오는 24개 공통 분기를 평가했습니다. 2019년 2·3분기 형성 포트폴리오는 선택된 SMCI의 미래 수익률이 사용한 CRSP 자료에서 누락되어 제외됐습니다. 포트폴리오 형성은 2019년 12월 말부터 2025년 9월 말까지이며 실현 수익률은 2020년 1월부터 2025년 12월까지입니다. 평가 분기의 제약과 현재 구성종목 선택의 영향을 고려해야 합니다." if full else "작은 선택 표본의 결과로 특정 접근법의 우월성을 확정하지 않습니다."),
        65, source_urls)
    rows = [["모델", "평균 IC", "RMSE", "비용 후 분기 평균"]]
    rows += [[labels.get(v["model"], v["model"]), fmt(v.get("mean_ic"), 4 if full else 3), fmt(v.get("rmse"), 4), fmt(v.get("net_quarterly_mean"), 2, True)] for v in models]
    if len(rows) == 1:
        rows.append(["학습 표본 부족", "미산출", "미산출", "미산출"])
    d.table(s, rows, 57, 141, 847, 255, [203, 166, 165, 313], 21)
    model_map = {v["model"]: v for v in models}
    base_rmse = model_map.get("baseline", {}).get("rmse")
    combined_rmse = model_map.get("combined", {}).get("rmse")
    if base_rmse and combined_rmse is not None:
        delta = 100 * (combined_rmse / base_rmse - 1)
        change = "증가" if delta >= 0 else "감소"
        d.text(s, f"결합 예측오차: 기준 모델 대비 {abs(delta):.1f}% {change}", 58, 414, 840, 33, 23, "teal", True)
    d.text(s, f"예측 {evaluated_periods}분기 · 롱숏 {portfolio_period_label}분기 · 과거 {meta['min_train_quarters']}분기 이상 학습" if full else f"수익률 평가 {evaluated_periods}분기 · 과거 {meta['min_train_quarters']}분기 이상으로만 학습", 58, 455, 840, 28, 18, "muted")
    d.text(s, "롱 100%·숏 100%, 거래금액당 10bp 비용 가정. 차입·자금조달·시장충격 비용 제외", 58, 487, 846, 21, 14, "muted")

    counts = [v for v in r["disagreement"]["summary"] if v["scope"] == "All" and v["topic"] == "overall"]
    c_lookup = {v["outcome"]: v["count"] for v in counts}
    outcomes = {"fed_toward_corporate": "연준이 기업 쪽으로", "corporate_toward_fed": "기업이 연준 쪽으로",
                "both_adjust": "양쪽 조정", "persistent_or_diverging": "지속·확대 또는 축소 미달"}
    leads = [v for v in r["disagreement"]["lead_lag"] if v["scope"] == "All" and v["topic"] == "overall"]
    s = d.slide("괴리 해소와 어조의 선후행",
        "전체 기업의 평균 어조와 FOMC 어조를 각각 과거 데이터로만 표준화했습니다. 두 표준화 점수의 차이 절댓값이 1 이상인 경우를 골라 다음 분기 격차가 25퍼센트 이상 줄었는지와 어느 쪽이 움직였는지 기록했습니다. 격차 자체를 다시 표준화하지 않았고, 다음 분기를 평가할 때도 최초 시점의 평균과 표준편차를 고정했습니다. 별도로 자기 자신의 과거 어조만 쓰는 모델에 다른 출처의 어조를 추가했을 때 다음 어조의 예측오차가 얼마나 줄었는지 확인했습니다. 이 분석은 상대적인 언어 변화에 대한 결과입니다. 물가와 고용에 대한 경제적 판단이 누구에게 더 정확했는지나 미래 투자수익의 우열을 직접 보여주지는 않습니다. 사후 해소 결과는 과거 투자 신호에 넣지 않았습니다.",
        60, source_urls)
    d.table(s, [["전체 어조 괴리의 다음 분기 변화", "건수"]] + [[name, str(c_lookup.get(key, 0))] for key, name in outcomes.items()],
            57, 137, 847, 241, [673, 174], 21)
    y = 402
    for row in leads:
        label = "기업 정보 추가: 연준 예측" if row["direction"] == "bottom_up_to_top_down" else "연준 정보 추가: 기업 예측"
        improvement = row["improvement_pct"]
        change = "감소" if improvement is not None and improvement >= 0 else "증가"
        label_value = f"{abs(improvement):.1f}% {change}" if improvement is not None else "미산출"
        d.text(s, f"{label} 오차 {label_value} ({row['n_oos']}분기)", 58, y, 846, 31, 19, "teal", True)
        y += 37
    if not leads:
        d.text(s, "선후행 표본 밖 예측: 학습 이력 부족으로 미산출", 58, y, 845, 35, 20, "muted")
    d.text(s, "상대적 어조의 수렴을 경제 전망의 정확성이나 투자 우위로 해석하지 않음", 58, 487, 845, 21, 15, "muted")

    s = d.slide("이번 결과의 범위와 후속 검증",
        "실제 공개 문서의 수집, 공통 주제별 점수화, 기업 수익률 연결, 표본 밖 예측과 괴리 분석을 실행했습니다. 다만 표본 선택과 생존편향, 현재 GICS의 고정 적용은 남아 있습니다. LM 어조는 매파성이나 원가와 수요의 경제적 방향을 구분하지 않으므로 의미에 대한 검증도 필요합니다. " + fb_note + " 사람 정답을 사용하지 않은 점수 일치도 비교이므로 분류 정확도를 검증한 결과도 아닙니다. 후속 분석에서는 과거 구성종목을 복원하고, 전체 코퍼스의 FinBERT 수익률 검증과 EPS 서프라이즈·실적 통제를 진행해야 합니다. " + ("이번 전수 대상 분석은 표본 확대와 원문 선택·추출 교정을 함께 반영했습니다. 따라서 이전 33개 기업 파일럿과의 차이를 표본 확대만의 효과로 해석할 수 없습니다. " if full else "") + "코드와 HTML에서 결과와 자료 출처를 함께 확인할 수 있습니다.",
        50, source_urls + (SOURCES["finbert"],))
    d.table(s, [
        ["이번 실행", "후속 검증"],
        ["현재 구성종목 전수 대상 수집" if full else "선택 기업·현재 GICS 표본", "역사적 구성종목·섹터 복원"],
        ["LM 어조·공통 주제 분류", "전체 코퍼스 FinBERT 수익률 검증"],
        ["3개월 수익률·표본 밖 예측", "실적·EPS 서프라이즈 통제"],
        ["어조 괴리·선후행 진단", "주제·섹터별 안정성 재확인"],
    ], 57, 141, 847, 260, [416, 431], 21)
    if fb_done:
        d.text(s, f"LM·FinBERT: {fb['documents']}문서·{fb['sentences']:,}문장의 점수 일치도 비교 완료", 58, 422, 845, 33, 20, "teal", True)
    d.text(s, f"점수 상관 {fb['lm_finbert_matched_spearman']:.3f} · 투자성과 비교는 후속 검증" if full and fb_done else "전체 코퍼스의 투자성과 비교는 후속 검증", 58, 467, 843, 33, 22, "navy", True)
    return d.finish()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--proposal", action="store_true")
    p.add_argument("--results", type=Path)
    p.add_argument("--full-results", type=Path,
                   help="Build results_full.pptx from frozen full_current_constituents results with explicit coverage denominators.")
    args = p.parse_args()
    if args.results and args.full_results:
        p.error("Use --results or --full-results, not both.")
    if args.proposal or not (args.results or args.full_results):
        proposal()
    if args.results:
        results(args.results)
    if args.full_results:
        results(args.full_results, require_full=True)


if __name__ == "__main__":
    main()
