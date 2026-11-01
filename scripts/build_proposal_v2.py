"""Build the six-slide, seven-minute proposal revision with native PowerPoint.

Uses genuine official PDF captures when website UI capture is unavailable.
The open original proposal is preserved; this revision is a separate file.
"""
from pathlib import Path
import json,hashlib,sys
import win32com.client
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'.build/slides/proposal_7min_v2'
OUT=ROOT/'presentations/proposal_7min_v2.pptx'
FONT='맑은 고딕'
C={'rust':'B05030','brown':'2C1810','text':'1E1E1E','charcoal':'3D3D3D','muted':'888888','pale':'F5F5F5','cream':'F0EDE8','line':'DEDEDE','blue':'154360','green':'1E6B44','purple':'512460','white':'FFFFFF'}
W,H=720,405

def rgb(v):
    h=C.get(v,v)
    return int(h[:2],16)+256*int(h[2:4],16)+65536*int(h[4:],16)

class Proposal:
    def __init__(self):
        BUILD.mkdir(parents=True,exist_ok=True)
        self.app=win32com.client.DispatchEx('PowerPoint.Application')
        self.p=self.app.Presentations.Add(False)
        self.p.PageSetup.SlideWidth=W;self.p.PageSetup.SlideHeight=H
        self.rows=[]

    def box(self,s,x,y,w,h,fill='pale',line=None,kind=1,name=None):
        a=s.Shapes.AddShape(kind,x,y,w,h)
        a.Fill.ForeColor.RGB=rgb(fill)
        a.Line.Visible=-1 if line else 0
        if line:a.Line.ForeColor.RGB=rgb(line)
        if name:a.Name=name
        return a

    def text(self,s,t,x,y,w,h,size=14,color='text',bold=False,align=1,name=None):
        a=s.Shapes.AddTextbox(1,x,y,w,h)
        a.Fill.Visible=0;a.Line.Visible=0
        f=a.TextFrame;f.MarginLeft=f.MarginRight=f.MarginTop=f.MarginBottom=0
        f.WordWrap=-1;f.AutoSize=0;f.VerticalAnchor=1
        f.TextRange.Text=t
        r=f.TextRange;r.Font.Name=FONT;r.Font.NameFarEast=FONT;r.Font.Size=size;r.Font.Bold=-1 if bold else 0;r.Font.Color.RGB=rgb(color)
        r.ParagraphFormat.Alignment=align;r.ParagraphFormat.SpaceAfter=3;r.ParagraphFormat.SpaceBefore=0
        a.Left=x;a.Top=y;a.Width=w;a.Height=h
        if name:a.Name=name
        return a

    def line(self,s,x,y,x2,y2,color='line',weight=.7,arrow=False):
        a=s.Shapes.AddLine(x,y,x2,y2);a.Line.ForeColor.RGB=rgb(color);a.Line.Weight=weight
        if arrow:a.Line.EndArrowheadStyle=3
        return a

    def slide(self,title,seconds,script,sources=(),cover=False):
        s=self.p.Slides.Add(self.p.Slides.Count+1,12)
        s.FollowMasterBackground=0;s.Background.Fill.ForeColor.RGB=rgb('white')
        self.box(s,0,0,16,405,'rust')
        if not cover:
            self.text(s,title,25,12,645,31,22,bold=True)
            self.line(s,25,49,705,49)
            self.box(s,16,380,704,25,'cream')
            self.text(s,'KAIST DFMBA | 금융데이터 애널리틱스 · Case 3',25,388,600,11,7.5,'muted')
            self.text(s,str(s.SlideIndex),680,386,25,13,9,'rust',True,3)
        else:
            self.box(s,0,0,720,76,'brown')
            self.text(s,'연구 제안',525,13,176,23,14,'white',True,3)
            self.text(s,'KAIST DFMBA | 금융데이터 애널리틱스',375,49,326,15,8.5,'CCBBAA',False,3)
        note=f'권장 발표 시간: {seconds}초\n\n{script}'
        if sources: note+='\n\n출처:\n'+'\n'.join(sources)
        s.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text=note
        self.rows.append({'slide':s.SlideIndex,'title':title,'seconds':seconds,'script':script,'sources':list(sources)})
        return s

    def bar(self,s,t,x,y,w,color='charcoal'):
        self.box(s,x,y,w,24,color);self.text(s,t,x+10,y+4,w-20,18,12,'white',True)

    def picture(self,s,name,x,y,w,h,link):
        path=ROOT/'presentations/assets/proposal'/name
        im=Image.open(path);iw,ih=im.size
        k=min(w/iw,h/ih);pw,ph=iw*k,ih*k
        a=s.Shapes.AddPicture(str(path),0,-1,x+(w-pw)/2,y+(h-ph)/2,pw,ph)
        a.ActionSettings(1).Hyperlink.Address=link
        a.Name='official_document_capture_'+path.stem
        return a

    def finish(self):
        for key,val in [('Title','연준의 말, 기업의 말 — 연구 제안'),('Subject','FOMC와 S&P 500 실적발표 텍스트의 결합 분석'),('Author','DFMBA Research')]:
            self.p.BuiltInDocumentProperties(key).Value=val
        candidate=BUILD/'candidate.pptx'
        self.p.SaveAs(str(candidate),24)
        qa={'slides':len(self.rows),'seconds':sum(v['seconds'] for v in self.rows),'native_renderer':'Microsoft PowerPoint','text_overflow':[],'off_slide':[],'website_capture_limitation':'Browser UI capture stopped because current URL could not be verified; genuine official PDF captures used instead.'}
        for s in self.p.Slides:
            s.Export(str(BUILD/f'slide-{s.SlideIndex:02}.png'),'PNG',1600,900)
            for sh in s.Shapes:
                if sh.Left < -.2 or sh.Top < -.2 or sh.Left+sh.Width>W+.2 or sh.Top+sh.Height>H+.2: qa['off_slide'].append({'slide':s.SlideIndex,'shape':sh.Name})
                if sh.HasTextFrame and sh.TextFrame.HasText:
                    f=sh.TextFrame
                    if f.TextRange.BoundHeight>sh.Height-f.MarginTop-f.MarginBottom+2:qa['text_overflow'].append({'slide':s.SlideIndex,'text':f.TextRange.Text,'bound':f.TextRange.BoundHeight,'height':sh.Height})
        self.p.Close()
        if self.app.Presentations.Count==0:self.app.Quit()
        if qa['text_overflow'] or qa['off_slide']:
            (BUILD/'qa.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding='utf-8')
            raise RuntimeError('Fix the recorded layout issues before delivery')
        OUT.write_bytes(candidate.read_bytes())
        qa['sha256']=hashlib.sha256(OUT.read_bytes()).hexdigest()
        (BUILD/'qa.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        canvas=Image.new('RGB',(1600,3*463),'#e9edf1')
        for i in range(6):
            im=Image.open(BUILD/f'slide-{i+1:02}.png');im.thumbnail((790,444));canvas.paste(im,((i%2)*800,(i//2)*463))
        canvas.save(BUILD/'contact-sheet.png')
        elapsed=0;parts=['# 제안 발표 수정본 대본\n\n총 6장, 권장 발표 시간 7분(420초).\n']
        for r in self.rows:
            end=elapsed+r['seconds'];parts.append(f"## {r['slide']}. {r['title']} ({elapsed//60}:{elapsed%60:02}–{end//60}:{end%60:02})\n\n{r['script']}\n")
            if r['sources']:parts.append('출처: '+'\n'.join(r['sources'])+'\n')
            elapsed=end
        (ROOT/'docs/presentation_script_v2.md').write_text('\n'.join(parts),encoding='utf-8',newline='\n')
        manifest={'file':OUT.relative_to(ROOT).as_posix(),'slides':6,'seconds':420,'sha256':qa['sha256'],'slide_order':self.rows,'reference_design':'최종발표_1조_v3.pptx — 720×405, Malgun Gothic, B05030/3D3D3D/F0EDE8','diagram':'Four editable native chevrons, all research steps on slide 5','data_capture':'Actual official PDF captures with source-site hyperlinks; not website UI screenshots','original_open_file_preserved':True}
        (ROOT/'presentations/proposal_revision.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps(qa,ensure_ascii=False,indent=2))

def main():
    d=Proposal()
    fed='https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
    jpm='https://www.jpmorganchase.com/ir/quarterly-earnings'
    src=json.loads((ROOT/'presentations/assets/proposal/sources.json').read_text(encoding='utf-8'))['sources']
    s=d.slide('연준의 말, 기업의 말',30,
        '저희는 미국 기업의 실적발표와 연준의 FOMC 의사록을 텍스트로 분석하는 연구를 제안합니다. 기업 현장에서 출발하는 바텀업 관점과 경제 전체를 보는 탑다운 관점을 같은 시간축에 놓고, 각각의 정보가 투자에 도움이 되는지, 결합하면 더 나아지는지 검증하려고 합니다. 수업의 Case 3에서 배운 공시 수집과 텍스트 추출이 출발점입니다.',cover=True)
    d.text(s,'연준의 말, 기업의 말',32,104,645,48,32,bold=True)
    d.text(s,'FOMC 의사록과 S&P 500 실적발표의 결합 분석',33,165,640,26,16,'7A5540')
    d.line(s,33,204,677,204,'rust',2.7)
    d.text(s,'거시 전망과 기업 전망을 함께 읽으면\n투자 판단이 나아질까?',33,229,410,72,22,bold=True)
    d.text(s,'Case 3 기반 연구 제안 · 약 7분',33,330,420,22,12,'muted')
    d.box(s,474,239,91,36,'blue');d.text(s,'연준의 전망',481,248,78,20,12,'white',True,2)
    d.box(s,474,291,91,36,'green');d.text(s,'기업의 전망',481,300,78,20,12,'white',True,2)
    d.line(s,565,257,598,282,'rust',1.7,True);d.line(s,565,309,598,284,'rust',1.7,True)
    d.box(s,600,265,96,39,'rust');d.text(s,'투자 판단',605,276,86,20,13,'white',True,2)

    s=d.slide('두 관점의 자료를 같은 시간축에서 읽는다',70,
        '탑다운 자료는 연준 공식 홈페이지의 FOMC 의사록입니다. 정례회의는 통상 연 여덟 차례이며, 의사록에는 성장과 수요, 물가, 고용, 투자와 금융여건에 대한 다양한 평가가 들어 있습니다. 바텀업 자료는 S&P 500 기업의 실적발표 보도자료입니다. SEC 공시에 첨부된 발표문을 중심으로 수집하고 기업의 공식 IR 자료를 함께 확인합니다. 오른쪽은 JPMorgan의 실제 실적발표 자료 예시입니다. 수치뿐 아니라 수요와 비용, 경영진의 설명과 가이던스를 텍스트로 분석할 계획입니다. 두 자료는 발표 빈도와 공개일이 다르므로, 각 시점에 실제 공개되어 있던 문서를 연결하는 것이 중요합니다. 화면의 이미지는 공식 사이트가 제공하는 실제 원문 PDF 발췌이며 웹페이지 UI 캡처는 아닙니다.',
        [fed,jpm,*[x['url'] for x in src]])
    d.bar(s,'TOP-DOWN  |  FOMC 의사록',25,63,326,'blue');d.bar(s,'BOTTOM-UP  |  S&P 500 실적발표',369,63,326,'green')
    d.text(s,'federalreserve.gov · 회의 일정과 의사록',30,94,320,18,10,'blue')
    d.text(s,'기업 IR · SEC EDGAR의 실적발표 자료',374,94,320,18,10,'green')
    d.box(s,25,116,326,165,'white','line');d.box(s,369,116,326,165,'white','line')
    d.picture(s,'fomc_minutes.png',30,120,130,157,fed)
    d.text(s,'Federal Open\nMarket Committee',174,139,166,45,16,'blue',True)
    d.text(s,'거시경제 평가의 원문\nPDF · HTML 제공\n정례회의 통상 연 8회',174,202,166,66,12)
    d.picture(s,'jpm_earnings.png',376,122,312,141,jpm)
    d.text(s,'JPMorganChase · 2025년 3분기 실적발표 예시',377,264,308,14,8.5,'muted')
    d.text(s,'물가 · 고용 · 성장 · 투자 · 금융여건',29,299,322,21,14,'blue',True)
    d.text(s,'수요 · 원가 · 실적 · 향후 가이던스',373,299,322,21,14,'green',True)
    d.text(s,'분석 범위: 2016–2025년 · 전체 기업과 GICS 11개 섹터',29,337,662,22,14,'rust',True)
    d.text(s,'이미지: 공식 사이트 제공 원문 PDF 발췌 · 이미지를 클릭하면 해당 자료 제공 사이트로 이동',29,366,666,11,7.5,'muted')

    s=d.slide('네 가지 연구 가설',75,
        '연구의 가설은 네 가지입니다. 첫째, 기업의 실적과 전망을 평가한 텍스트 점수가 높을수록 이후 시장 대비 수익률이 높을 것이라는 가설입니다. 둘째, 연준의 경기 인식과 전망은 이후 시장과 섹터 수익률에 관련될 것이라고 봅니다. 셋째, 물가와 고용 등 같은 거시 주제도 섹터별로 전달 경로가 달라, 주제별 정보의 추가 예측력 역시 다를 수 있습니다. 예를 들어 임금은 비용이고 고용은 수요와도 연결됩니다. 넷째, 기업과 연준의 전망이 엇갈리면 어느 쪽이 먼저 변화를 포착하는지 비교합니다. 기업을 따라갈지 연준을 따라갈지 미리 정하지 않고, 주제와 섹터별 차이와 실제 수익률을 확인해 초점을 정하려고 합니다.')
    hypotheses=[('H1','기업 점수와 수익률','실적·전망 점수가 높은 기업일수록\n이후 시장 대비 수익률이 높을 것이다.','rust'),('H2','연준 전망과 수익률','연준의 경기 인식은 시장·섹터의\n이후 수익률과 관련될 것이다.','blue'),('H3','거시 주제 × 섹터','물가·고용 등 주제별 정보의\n추가 예측력은 섹터마다 다를 것이다.','green'),('H4','괴리와 선행 정보','전망이 엇갈리면 어느 쪽이\n먼저 변화를 포착하는가?','purple')]
    for i,(code,title,body,color) in enumerate(hypotheses):
        x=25+(i%2)*344;y=67+(i//2)*135
        d.box(s,x,y,326,119,'pale','line');d.box(s,x,y,5,119,color)
        d.box(s,x+14,y+13,35,27,color,kind=9)
        d.text(s,code,x+15,y+18,33,18,12,'white',True,2)
        d.text(s,title,x+60,y+17,253,24,16,color,True)
        d.text(s,body,x+18,y+60,300,49,14)
    d.text(s,'검증 단위: 전체 기업 + GICS 섹터  |  판단 기준: 공개 이후의 수익률',30,350,665,24,13,'rust',True)

    s=d.slide('텍스트를 비교 가능한 점수로 바꾼다',75,
        '텍스트를 점수로 바꾸는 방법은 사전 방식과 문맥 모델을 비교합니다. 먼저 공시와 의사록에서 분석할 본문을 추출하고 반복되는 법적 문구를 정리합니다. 전체 실적 설명과 미래 전망을 담은 문장을 구분해서 보려고 합니다. LM 금융 사전은 긍정과 부정 단어의 차이, 그리고 불확실성 단어의 비율을 계산하는 방식입니다. FinBERT는 문장 전체를 보고 긍정과 부정, 중립의 확률을 내므로, 이를 문서 단위로 집계해 사전 점수와 비교할 수 있습니다. 불확실성은 별도 사전 지표로 유지합니다. 두 자료에는 물가, 고용, 성장과 수요, 투자, 금융여건이라는 공통 주제 태그를 붙입니다. 특히 긍정적인 문장이 곧 긴축 또는 경기 개선을 뜻하는 것은 아니므로 경제적 방향과 가이던스의 의미는 문장 표본을 읽어 점검할 계획입니다.',
        ['https://sraf.nd.edu/loughranmcdonald-master-dictionary/','https://huggingface.co/ProsusAI/finbert'])
    d.bar(s,'본문 추출 → 반복 문구 정리 → 실적 설명과 미래 전망 문장 구분',25,65,670)
    d.text(s,'“수요 개선을 예상하지만, 투입비용에는 불확실성이 남아 있다.”',39,110,644,31,17,bold=True)
    d.text(s,'이해를 돕기 위한 가상 문장 번역 · 실제 분석은 영문 원문 사용',39,143,644,15,9,'muted')
    for x,color,title,body in [(25,'rust','LM 금융 사전','긍정·부정 단어의 차이\n전체 단어 대비 비율로 점수화\n불확실성은 별도 지표로 계산'),(369,'blue','FinBERT 문맥 모델','문장별 긍정·부정·중립 확률\n긍정 확률 − 부정 확률을 집계\n동일 문장에서 사전 점수와 비교')]:
        d.bar(s,title,x,182,326,color);d.box(s,x,208,326,98,'pale','line');d.text(s,body,x+15,224,296,75,14)
    d.text(s,'공통 주제 태깅',26,326,121,22,13,bold=True)
    for i,(label,color) in enumerate([('물가','rust'),('고용','blue'),('성장·수요','green'),('투자','purple'),('금융여건','charcoal')]):
        x=146+i*110;d.box(s,x,322,102,30,color);d.text(s,label,x+4,329,94,18,12,'white',True,2)

    s=d.slide('연구 진행 순서: 4단계 검증',100,
        '연구는 네 단계로 진행하며 전체 기업과 각 섹터에서 같은 질문을 비교합니다. 첫 단계는 기업 텍스트의 유효성입니다. 기업의 실적과 전망 어조를 다음 3개월 시장 대비 수익률에 연결해, 점수가 높은 기업의 성과가 더 좋은지 봅니다. 두 번째는 연준 정보를 추가하는 단계입니다. 섹터와 과거 모멘텀을 공통 통제로 두고, 기준 모델과 기업 텍스트 모델, 연준 텍스트 모델, 결합 모델을 같은 기업과 기간에서 비교합니다. 세 번째는 주제와 섹터의 차이입니다. 기업과 연준의 같은 주제 변수를 함께 제외했을 때 예측 오차가 어떻게 변하는지 비교해 추가 기여를 봅니다. 이는 FOMC만의 기여나 인과효과의 추정과는 구분합니다. 네 번째는 괴리와 선후행입니다. 기업과 연준의 표준화 어조 차이가 클 때 다음 분기 어느 쪽이 조정되는지 살피고, 다른 쪽 정보를 추가했을 때 다음 어조를 더 잘 예측하는지도 확인합니다. 모든 단계는 실제 공개일을 기준으로 문서를 연결하고, 과거 자료로 학습한 뒤 이후 기간에서 평가합니다. 괴리가 줄어든다는 사실과 실제 투자 수익을 얻는다는 것은 따로 확인합니다.')
    stages=[('01','기업 텍스트','기업 점수와 미래 수익률','전체·동일 섹터에서\n점수와 수익률을 연결','IC · 상위−하위 성과','rust'),('02','FOMC 결합','연준 정보의 추가 가치','기준·기업·연준·결합\n네 모델을 같은 표본에 적용','RMSE · 평균 IC','blue'),('03','주제·섹터','주제별 추가 기여','해당 주제 변수를 제외해\n전체·섹터별 차이를 비교','주제 제외 후 오차 변화','green'),('04','괴리 분석','어느 쪽이 먼저인가','괴리의 다음 변화와\n양방향 어조 예측을 비교','괴리 축소 · 예측 개선','purple')]
    for i,(n,title,question,body,metric,color) in enumerate(stages):
        x=25+169*i
        d.box(s,x,77,163,63,color,kind=52,name=f'research_step_{n}')
        d.text(s,f'{n}\n{title}',x+29,84,106,50,14,'white',True,2)
        d.text(s,question,x+4,162,155,40,13,color,True,2)
        d.text(s,body,x+4,216,155,48,12,'text',False,2)
        d.line(s,x+4,273,x+157,273,'line')
        d.text(s,metric,x+3,286,157,35,11.5,color,True,2)
    d.box(s,25,337,670,27,'cream')
    d.text(s,'공개일 정렬  →  분기 패널 연결  →  과거 학습·이후 검증  |  전체 + 섹터별 비교',32,343,655,18,12,'rust',True,2)

    s=d.slide('검증 설계와 투자 활용',70,
        '마지막으로 예측력의 개선이 실제 투자 활용으로 이어지는지 평가합니다. 같은 섹터와 모멘텀을 사용하는 기준 모델을 두고 기업 텍스트, 연준 텍스트, 두 정보를 결합한 모델이 무엇을 더하는지 비교합니다. 바텀업 정보의 효용이 확인되면 같은 섹터 내 종목선정에 활용할 수 있습니다. 탑다운 정보의 효용이 확인되면 거시 노출과 섹터 비중 조절의 후보가 됩니다. 결합 정보가 안정적으로 더 좋다면 결합 예측값에 따른 비중 결정을 검토합니다. 평가에서는 순위 예측력인 IC, 수익률 예측 오차인 RMSE, 거래비용을 차감한 롱숏 성과를 함께 봅니다. 학습 구간 이후의 미래 기간에서 같은 기준으로 비교하고, 여러 기간에 걸쳐 결과가 유지되는지도 확인합니다. 저희가 최종적으로 답하려는 질문은 텍스트 정보의 추가 예측력이 투자성과로 이어지는가입니다.')
    d.bar(s,'같은 통제변수에서 비교',25,65,291)
    d.bar(s,'효용이 확인됐을 때의 투자 활용',355,65,340)
    rows=[('기준: 섹터 + 모멘텀','추가 효용을 판단하는 기준','charcoal'),('기업 텍스트 추가','동일 섹터 내 종목선정','green'),('연준 텍스트 추가','거시 노출·섹터 비중 조절','blue'),('기업 + 연준 정보 결합','결합 예측값에 따른 비중 결정','rust')]
    for i,(left,right,color) in enumerate(rows):
        y=97+i*43
        d.box(s,25,y,291,35,'pale','line');d.box(s,25,y,4,35,color)
        d.text(s,left,38,y+8,271,23,14,color,True)
        d.line(s,325,y+17,345,y+17,'rust',1.2,True)
        d.box(s,355,y,340,35,'pale','line');d.text(s,right,369,y+8,314,23,14)
    d.box(s,25,288,670,39,'cream')
    d.text(s,'과거 구간 학습  →  이후 구간 검증',35,298,314,23,14,'rust',True)
    d.text(s,'IC · RMSE · 거래비용 차감 성과',357,298,326,23,13,'charcoal',True)
    d.text(s,'텍스트 정보의 추가 예측력이 투자성과로 이어지는가?',28,346,665,27,17,'rust',True,2)
    d.finish()

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
