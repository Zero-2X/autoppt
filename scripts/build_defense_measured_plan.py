"""Reviewed reconstruction measurements for the 11 existing ImageGen masters."""
from pathlib import Path
import json, re

RUN=Path(__file__).resolve().parents[1]/'runs'/'zhengzhangxuan_defense_20260920'
brief=json.loads((RUN/'slide_brief.json').read_text(encoding='utf-8'))
W,H=1672,941
INK='20242B'; RED='A72124'; GRAY='B7B9BD'; PALE='DDDDE0'
deck={'title':brief['deck_title'],'author':'张正轩','units':'pixel','ref_width':W,'ref_height':H,'slide_width_in':13.333333,'slide_height_in':7.5,'slides':[]}
s=None
def slide(i,bg='F0EFEB'):
    global s
    b=brief['slides'][i-1]
    s={'slide_id':f'S{i:02d}','source':str(RUN/'masters'/f'{b["slide_id"]}.png'),'background_color':bg,'texts':[],'shapes':[],'assets':[],
       'notes':'[Sources]\n'+str(RUN/'thesis_evidence.json')+'\n原论文：'+str(Path('C:/Users/XC/Desktop/毕业设计/张正轩毕业设计论文定稿.docx'))+'\n讲述要点：\n'+'\n'.join(b['content'])+'\n[Visual provenance]\n图像局部来自本次 ImageGen 母版，用于示意，不作为实际监控截图或原始实验散点。普通文字、框图、连接线和图标重建为原生对象。'}
    if i in (2, 6, 7):
        # These masters intentionally use a high-contrast, all-bold chapter
        # treatment. Record the exception so the layout guard does not mistake
        # the measured style for an accidental bold cascade.
        s['allow_all_bold_text'] = True
        s['qa_note'] = 'Measured master uses all-bold chapter treatment; retained intentionally.'
    deck['slides'].append(s)
def text(t,x,y,w,h,px=32,bold=False,color=INK,font='SimSun',align='left',name=None):
    name=name or f'{s["slide_id"]}-text-{len(s["texts"])+1:03d}'
    # Fixed line breaks and measured frames make output independent of OCR guesses.
    item={'name':name,'text':t,'x':x,'y':y,'w':w,'h':h,'source_bbox':[x,y,w,h],'layout_bbox':[x,y,w,h],'size':px*960/W,'font':font,'bold':bold,'color':color,'align':align,'valign':'middle','fit':'shrink','editability_level':'native-reviewed','verified_by':'full-master-measurement'}
    # Latin text uses the serif family measured in the master.
    if font=='SimSun':
        item['runs']=[{'text':p,'font':'Times New Roman' if re.fullmatch(r'[\x00-\x7f×→]+',p) else 'SimSun'} for p in re.findall(r'[\x00-\x7f×→]+|[^\x00-\x7f×→]+',t)]
    s['texts'].append(item); return item
def shape(x,y,w,h,fill=None,line=GRAY,type='rect',width=1,z=10,name=None,**kw):
    d={'name':name or f'{s["slide_id"]}-shape-{len(s["shapes"])+1:03d}','type':type,'x':x,'y':y,'w':w,'h':h,'source_bbox':[x,y,w,h],'layout_bbox':[x,y,w,h],'line':line,'line_width':width,'z_index':z,'editability_level':'native-reviewed',**kw}
    if fill: d['fill']=fill
    if line is None: d['line']=fill or 'FFFFFF';d['line_opacity']=0
    s['shapes'].append(d);return d
def line(x,y,x2,y2,color=INK,width=1,arrow=False,dash=None):
    # Keep a non-zero measured bbox for horizontal/vertical lines. The
    # renderer still uses x1/y1/x2/y2, while QA tools can validate the box.
    return shape(min(x,x2),min(y,y2),max(abs(x2-x),1),max(abs(y2-y),1),line=color,type='line',width=width,z=20,x1=x,y1=y,x2=x2,y2=y2,**({'end_arrow':'triangle'} if arrow else {}),**({'dash':dash} if dash else {}))
def box(t,x,y,w,h,px=30,fill=None,color=INK,bold=False,dash=None):
    shape(x,y,w,h,fill=fill,line=INK,type='rounded_rect',width=.8,**({'dash':dash} if dash else {}))
    text(t,x+10,y+5,w-20,h-10,px,bold,color,align='center')
def crop(name,x,y,w,h,trace=False,ink='dark',color=INK):
    s['assets'].append({'name':name,'source_bbox':[x,y,w,h],'route':'native-trace' if trace else 'movable-image','ink':ink,'color':color,'reason':'bounded complex scientific/scene illustration from verified ImageGen master' if not trace else 'isolated flat icon converted to editable OOXML contours'})
def header(t,x=50,y=35,w=1570,h=88,px=64): text(t,x,y,w,h,px,True)
def page(n): text(f'{n:02d}',1600,885,42,42,26,font='Times New Roman')
def grid(x,y,w,rowh,rows,colwidths,px=32):
    for r,row in enumerate(rows):
        cx=x
        for c,value in enumerate(row):
            cw=w*colwidths[c]
            shape(cx,y+r*rowh,cw,rowh,line='65676A',width=.65)
            text(value,cx+18,y+r*rowh+5,cw-36,rowh-10,px,c==len(row)-1,RED if c==len(row)-1 else INK,align='left' if c==0 else 'center')
            cx+=cw

slide(1,'ECEBE8')
# The ImageGen title is a single measured line.  Native fonts have different
# glyph widths, so reserve the full title span and use a slightly smaller
# optical size instead of allowing an accidental second line.
header(brief['deck_title'],82,78,1508,88,58)
text('从视觉感知到可复核监管信息的工程链路',84,190,1480,72,56)
line(84,320,1588,320,'B72C30',2.3)
text('毕业设计答辩',84,359,620,82,53)
text('张正轩｜船海与能源动力工程学院',1115,360,476,40,27,align='right')
text('指导教师：冯辉 教授',1130,407,460,42,27,align='right')
crop('bridge-scene',33,481,1606,423)

slide(2,'EAEAEA')
text('02',42,15,87,90,72,True,font='Arial');line(149,28,149,94,RED,1.5)
text('为什么要做桥区船舶智能监管',182,23,1430,82,62,True,font='Microsoft YaHei')
line(42,121,1630,121,width=.8)
text('桥区通航空间受限、船舶交汇频繁、桥墩与岸线遮挡明显，风险变化快',42,154,1580,62,42,True,font='Microsoft YaHei')
crop('bridge-monitoring',42,229,901,494)
labels=['可视化监管手段不足','AIS更新滞后且覆盖不全','身份切换与轨迹中断','单目测速误差','疑似违规难以结构化留痕']
for i,(lab,cy) in enumerate(zip(labels,[263,365,467,571,680])):
    shape(1115,cy-43,515,85,'DEDEDF',None,'rounded_rect');shape(1072,cy-48,97,97,'D2D3D3',None,'oval')
    crop(f'problem-icon-{i+1}',1086,cy-33,70,68,True)
    ti=text(lab,1202,cy-27,414,54,31,True,font='Microsoft YaHei')
    terms=['不足','滞后','不全','中断','误差','难以结构化留痕']
    ti['runs']=[{'text':p,'color':RED if p in terms else INK} for p in re.split('('+'|'.join(terms)+')',lab) if p]
    line(987,cy,1053,cy,width=1.3);shape(1047,cy-6,12,12,INK,None,'oval')
line(987,263,987,751,width=1.3);line(987,751,836,751,width=1.3);line(836,751,836,791,width=1.3,arrow=True)
shape(42,796,1588,107,'B4262B',None,'rounded_rect')
crop('goal-target',122,811,80,79,True,'white','FFFFFF')
line(258,813,258,885,'FFFFFF',.8)
text('研究目标：',307,819,210,63,43,True,'FFFFFF',font='Microsoft YaHei')
text('把检测、跟踪、测速、区域规则、预警与证据归档连接成一条可复核链路',525,822,1072,58,34,True,'FFFFFF',font='Microsoft YaHei')

slide(3,'F5F4F1')
header('总体思路：以轨迹为纽带贯通感知与监管',59,108,1540,88,69)
line(53,223,1621,223,RED,1.15)
xs=[35,445,853,1262]
names=['数据层','感知层','状态层','监管层']
caps=['长江航段桥区可见光视频 +\nAIS参照轨迹','YOLO11s检测 → BoT-SORT跟踪','底边中点轨迹 + 多点光流 +\n卡尔曼滤波 → 速度与方向','AIS弱监督校正 → 电子围栏/计数线/\n规则判断 → 预警与证据留痕']
for i,x in enumerate(xs):
    shape(x,272,377,525,line='ABADB3',type='rounded_rect',width=.7)
    shape(x+25,287,65,65,'B5090D',None,'oval')
    text(f'{i+1:02d}',x+29,291,56,52,38,True,'FFFFFF',font='Arial',align='center')
    text(names[i],x+118,294,246,63,43,True)
    crop(f'pipeline-scientific-panel-{i+1}',x+14,367,349,313)
    text(caps[i],x+14,702,350,77,27,font='Microsoft YaHei',align='center')
    if i<3: shape(x+374,498,42,42,'B51316',None,'right_arrow',z=110)

slide(4,'EEEDE9')
shape(35,71,8,50,RED,None);text('04',63,60,65,77,57,True,RED);line(146,71,146,124)
header('数据集与桥区场景难点',181,55,1420,84,69)
for name,b in zip(['day','night','fog','occlusion'],[(35,175,398,257),(444,175,404,257),(35,440,398,261),(444,440,404,261)]): crop(name,*b)
text('6180',887,166,175,93,83,True,RED,font='Times New Roman');text('张桥区可见光图像',1070,180,559,77,56,True)
text('白天｜夜间｜雨雾｜反光｜远距离小目标｜交汇｜岸边遮挡',890,267,747,47,30)
for i,(lab,pct,bw) in enumerate([('浮标','75.08%',326),('散货船','13.18%',66),('客船','7.35%',37),('集装箱船','4.39%',22)]):
    y=338+i*69.5;line(888,y,1637,y,'CBCBCB',.6)
    text(lab,894,y+13,151,47,32)
    shape(1052,y+20,450,32,'D7D7D7',None);shape(1052,y+20,bw,32,'AD5555',None)
    text(pct,1528,y+12,109,47,32,font='Times New Roman')
line(888,616,1637,616,'CBCBCB',.6);line(1035,338,1035,616,'D0D0D0',.6)
text('按视频片段划分训练/验证/测试集，避免相邻帧跨集合造成数据泄露',889,650,750,48,26)
line(36,744,1638,744,'AAAAAA',.6)
for i,(x,w,t) in enumerate([(36,461,'漏检 → 轨迹中断'),(567,544,'定位偏差 → 测速与围栏不稳'),(1178,459,'类别混淆 → 统计偏差')]):
    shape(x,778,w,103,line='C6C6C6',type='rounded_rect',width=.6)
    shape(x+33,791,79,79,'A44343',None,'oval')
    crop(f'impact-icon-{i}',x+44,801,58,59,True,'white','FFFFFF')
    text(t,x+140,799,w-148,64,31)
    if i<2: text('→',x+w+13,801,48,62,49,True,'A44343')

slide(5)
# Keep the long model title on one line in the editable reconstruction.
header(brief['slides'][4]['title'],55,40,1550,88,56)
line(43,156,1634,156,'606469',.8)
for x,w in [(43,211),(265,208),(483,209),(703,239)]: shape(x,245,w,457,line='ABABAB',width=.7,dash='dash')
for t,x,w in [('Input',60,175),('Backbone',286,165),('Neck',515,152),('Detect Head',727,199)]:text(t,x,278,w,46,31,True,font='Times New Roman',align='center')
for j in range(4):shape(90-j*7,361+j*7,135,142,line=INK,width=.7)
crop('input-vessel',72,383,134,138)
text('输入 640×640\nbatch size=16',62,561,198,76,30)
shape(287,327,161,306,line='999999',width=.6,dash='dash')
for y in [355,455,575]:
    shape(305,y,112,36,'B9C5CE',INK,width=.7)
    # Shallow 3D faces are native polygons/lines measured from the master.
    line(305,y,317,y-12,width=.65);line(317,y-12,430,y-12,width=.65);line(430,y-12,417,y,width=.65);line(430,y-12,430,y+23,width=.65);line(430,y+23,417,y+36,width=.65)
for y1,y2 in [(391,439),(491,533)]:line(363,y1,363,y2,arrow=True)
text('…',344,522,55,37,36,bold=True)
shape(518,327,149,306,line='999999',width=.6,dash='dash')
for y in [341,434,567]:shape(541,y,105,47,'B9C5CE',INK,width=.7)
line(593,388,593,429,arrow=True);line(593,542,593,483,arrow=True);text('…',570,526,53,31,34,True)
shape(727,327,195,306,line='999999',width=.6,dash='dash')
for y in [347,440,550]:
    for j in [2,1,0]:shape(790+j*6,y+12-j*6,97,48,'E8CECE',INK,width=.65)
text('P3/P4/P5多尺度输出',720,640,227,40,26)
line(239,437,286,437,arrow=True);line(437,467,473,467);line(473,467,473,364);line(473,364,537,364,arrow=True);line(434,588,538,588,arrow=True)
line(646,381,785,381,arrow=True);line(646,456,666,456);line(666,456,666,474);line(666,474,786,474,arrow=True);line(646,589,786,589,arrow=True)
line(972,206,972,763,'626262',.8)
shape(1005,206,629,176,line='626262',width=.7);line(1005,287,1634,287,'626262',.7)
text('YOLO11s',1020,214,600,65,53,True,font='Times New Roman')
for x in [1149,1316,1462]:line(x,287,x,382,'626262',.7)
for t,x,w in [('9.4M参数',1020,120),('21.5 GFLOPs',1166,141),('输入\n640×640',1328,124),('batch size=16',1470,154)]:text(t,x,297,w,77,28,align='center')
grid(1007,405,626,69,[['Precision=1.000','1.000'],['Recall=1.000','1.000'],['mAP@0.5=0.995','0.995'],['mAP@0.5:0.95=0.943','0.943'],['CPU复核约33 FPS','33 FPS']],[.61,.39],32)
shape(39,786,1595,91,'EBD1CE',None)
text('误差边界：夜间、遮挡、少样本集装箱船',67,797,1530,67,43,True,'8F1518');page(5)

slide(6)
header(brief['slides'][5]['title'],48,25,1580,90,65)
for i,(y,h) in enumerate([(143,181),(328,192),(524,189),(716,186)]): crop(f'trajectory-frame-{i}',38,y,681,h)
box('交汇、遮挡、检测框抖动 → 轨迹中断与ID切换',759,160,866,82,32,dash='dash')
line(1180,242,1180,296,arrow=True)
for i,(x,w,t) in enumerate([(751,159,'Kalman预测'),(937,157,'高/低置信度\n分级关联'),(1124,160,'IoU + Re-ID\n外观特征'),(1312,161,'全局运动补偿'),(1501,137,'轨迹管理')]):
    box(t,x,304,w,121,27,bold=True)
    if i<4:line(x+w,365,x+w+25,365,arrow=True)
shape(745,465,893,234,line=INK,type='rounded_rect',width=.7,dash='dash')
for i,t in enumerate(['MT=100%','ML=0','FM=38','IDSW=0']):
    shape(760+i*215.25,497,215.25,81,line=INK,width=.7);text(t,771+i*215.25,509,195,56,32,True,align='center')
for i,t in enumerate(['MOTA=96.75%','IDF1=98.38%','MOTP=90.56%']):
    shape(760+i*287,578,287,86,line=INK,width=.7);text(t,778+i*287,593,255,55,34,True,RED,align='center')
shape(746,740,892,151,line='737373',type='rounded_rect',width=.65)
text('● 身份保持为测速、流量统计、区域状态和异常行为判断提供稳定输入',772,763,843,48,29,True)
text('● 岸边遮挡仍产生少量轨迹碎片',772,820,843,47,29,True)

slide(7)
text('07',49,20,114,99,90,True,font='Times New Roman');line(184,38,184,113,'888888',.8)
header(brief['slides'][6]['title'],215,30,1415,88,57)
line(38,130,1635,130,'555555',.8);crop('dense-trajectory-map',39,177,473,700)
shape(536,174,335,495,line='B1B1B1',type='rounded_rect',width=.7,dash='dash');shape(892,174,330,495,line='B1B1B1',type='rounded_rect',width=.7,dash='dash')
text('视觉轨迹',557,183,296,51,35,True,align='center');text('AIS参照轨迹',910,183,294,51,35,True,align='center')
crop('visual-vessel-sequence',556,241,293,168);crop('ais-track-illustration',911,240,294,182)
box('底边中点 + 多点光流',555,458,298,77,30,fill='DEDEDE',bold=True);box('卡尔曼滤波',555,581,298,72,30,fill='DEDEDE',bold=True)
box('时间/空间/方向/形状综合匹配',904,460,308,76,26,fill='DEDEDE',bold=True);box('6208条弱监督样本',904,581,308,72,30,fill='DEDEDE',bold=True)
for x,y1,y2 in [(704,409,453),(704,535,577),(1058,422,455),(1058,536,577)]:line(x,y1,x,y2,arrow=True)
line(704,653,704,757);line(704,757,750,757,arrow=True);line(1058,653,1058,757);line(1058,757,1016,757,arrow=True)
shape(754,713,257,85,'E6B9B5',RED,'rounded_rect',width=.7);text('MLP',770,728,225,57,40,True,RED,align='center');line(883,798,883,841,arrow=True)
line(1253,172,1253,882,'AAAAAA',.7,dash='dash')
for idx,(y,label,color) in enumerate([(174,'RMSE 2.054 m/s',INK),(521,'RMSE 0.634 m/s',RED)]):
    shape(1286,y,348,284,line='AAAAAA',type='rounded_rect',width=.7)
    text(label,1303,y+7,315,54,35,True,color,align='center')
    crop(f'scatter-illustration-{idx}',1320,y+62,291,196)
shape(1446,468,31,44,'A94343',None,'down_arrow')
text('改善69.15%',1296,807,338,70,47,True,RED,align='center')

slide(8,'ECE9E5')
header(brief['slides'][7]['title'],59,19,1560,83,63)
ys=[117,252,386,523,662,798]
labels=['视频输入层','目标感知层','轨迹与状态层','规则统计层','界面交互层','数据存储层']
details=['本地视频/网络流、帧编号与时间戳','YOLO11s检测、BoT-SORT跟踪、track_id与历史轨迹','速度、方向、区域状态与质量标记','电子围栏、桥区禁入区、统计线、流量与疑似事件','监控画面、统计、告警、目标详情','关键帧、SQLite事件记录、日志与配置版本']
for i,y in enumerate(ys):
    shape(57,y,1099,112,line='B2463D',width=.8);shape(57,y,85,112,'AF473C',None)
    text(f'{i+1:02d}',67,y+26,65,62,40,False,'FFFFFF',align='center')
    text(labels[i],182,y+21,222,71,39,True)
    line(412,y+19,412,y+96,'626262',.65)
    text(details[i],446,y+26,697,61,31)
    shape(1170,y,446,112,line='B2463D',width=.8)
    if i<5:crop(f'system-layer-image-{i}',1175,y+6,435,102)
    else:
        crop('archive-keyframes',1190,810,235,93)
        line(1435,857,1489,857,arrow=True)
        crop('archive-database',1501,811,82,89,True)
    if i<5:shape(756,y+112,22,22,'B2463D',None,'down_arrow')

slide(9,'F1F2EF')
header(brief['slides'][8]['title'],49,41,1575,87,64)
line(50,142,1625,142,'565E66',.8);crop('monitoring-region-illustration',47,172,808,698)
def panel(y,h,title):
    shape(892,y,735,h,'FAFAFA','BAC0C6','rounded_rect',width=.7)
    shape(894,y+2,731,54,'DFE0DE',None)
    text(title,924,y+4,680,53,34,True)
panel(173,114,'区域配置');text('桥墩禁入区、预警区、主航道、横驶区、统计线、自定义作业区',927,237,684,43,26,font='Microsoft YaHei')
panel(326,189,'规则判断');text('连续轨迹 + 速度/方向 + 区域关系 + 持续时间',927,390,675,45,27,font='Microsoft YaHei')
for i,t in enumerate(['并行/追越','错走航路','航速异常','船位异常']):
    shape(924+i*171,442,161,54,'E94926',None,'rounded_rect');text(t,932+i*171,449,145,41,26,color='FFFFFF',font='Microsoft YaHei',align='center')
panel(554,140,'触发规则')
for i,t in enumerate(['告警列表','关键帧截图','SQLite事件记录']):
    shape(924+i*227,622,211,54,line='ACB3BB',type='rounded_rect',width=.7);text(t,934+i*227,630,191,37,26,font='Microsoft YaHei',align='center')
shape(892,732,735,56,'DFE0DE','BAC0C6','rounded_rect',width=.7);text('人工复核与追溯',924,735,680,49,35,True)
for y in [294,522,700]:shape(1242,y,28,26,'777B7C',None,'down_arrow')
shape(892,811,736,60,line='626970',width=.7,dash='dash')
text('track_id | timestamp | location | severity | evidence_path | rule_ids | config_version',908,824,705,36,21,font='Arial');page(9)

slide(10)
text('10',53,29,42,38,29,color='888888');line(52,70,82,70,'A4A3A0',1.5)
header(brief['slides'][9]['title'],129,58,1440,98,66)
for x in [562,1085]:line(x,197,x,574,'C9C7C3',.7)
for i,(x,t) in enumerate([(75,'检测'),(630,'跟踪'),(1156,'测速')]):
    shape(x,192,112,111,'E0DEDA',None,'oval');crop(f'metric-icon-{i}',x+24,217,67,65,True,'red','8E1D19')
    text(t,x+137,209,298,81,53,True);line(x,314,x+439,314,'C4C1BC',.65)
for i,(t,x,y,w) in enumerate([('Precision/Recall=1.000',75,337,447),('mAP@0.5=0.995',75,394,447),('mAP@0.5:0.95=0.943',75,450,447),('约33 FPS',75,505,447),('MOTA=96.75%',629,337,416),('IDF1=98.38%',629,394,416),('IDSW=0',629,450,416),('MT=100%',629,505,416),('MLP校正RMSE=0.634 m/s',1157,338,469),('原始2.054 m/s',1157,398,469),('下降69.15%',1157,464,469)]):
    item=text(t,x,y,w,54,40)
    item['runs']=[{'text:p':p} for p in []] if False else [{'text':p,'color':RED if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?%?',p) else INK,'font':'Times New Roman' if p.isascii() else 'SimSun','bold':bool(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?%?',p))} for p in re.split(r'([0-9]+(?:\.[0-9]+)?%?)',t) if p]
shape(44,652,77,77,'E0DEDA',None,'oval');crop('system-gear',60,668,42,45,True)
text('系统',142,657,100,64,43,True)
xs=[253,434,605,775,946,1117,1262,1452];ww=[144,135,134,134,134,108,154,176]
labs=['视频接入','检测跟踪','速度方向','流量统计','区域规则','告警','关键帧','数据库留痕']
for i,(x,w,lab) in enumerate(zip(xs,ww,labs)):
    shape(x,620,w,126,line='AAA8A4',type='rounded_rect',width=.65)
    # Each isolated icon is traced from the same master, preserving the drawing.
    cx=x+w/2;crop('system-icon-'+str(i),int(cx-32),637,64,51,True)
    text(lab,x+7,696,w-14,42,29,align='center')
    if i<7:line(x+w+9,684,xs[i+1]-9,684,'444444',1,True)
line(42,782,1628,782,'C9C6C1',.65);line(168,835,168,885,RED,2.4)
text('核心贡献：',199,822,225,75,47,True,RED);text('把算法指标转译为可展示、可追溯、可复核的监管信息',429,824,1170,73,45,True)

slide(11)
shape(62,53,13,69,'A52A28',None);header('结论与展望',107,33,399,99,75)
line(520,101,1614,101,RED,1)
for x in [541,1048]:line(x,191,x,651,'C3C0BC',.65)
for i,(x,t,iw) in enumerate([(63,'结论',106),(588,'当前边界',105),(1107,'下一步',105)]):
    shape(x,192,iw,103,'E4D1CD',None,'oval');crop('conclusion-icon-'+str(i),x+25,211,57,66,True,'red','A12824')
    text(t,x+137,201,290,74,50,True);line(x+138,283,x+229,283,RED,2)
text('完成桥区船舶检测、连续跟踪、\n速度估计、AIS校正、区域分析、\n辅助预警和证据留痕的整体原型',61,329,448,154,32)
for y,t,h in [(329,'数据类别/天气分布仍不均衡',49),(389,'遮挡与夜间场景存在检测和\n轨迹碎片',91),(491,'规则引擎尚缺长期实水域验证',54)]:
    shape(588,y+15,15,15,RED,None,'oval');text(t,624,y,403,h,31)
for y,t,h in [(321,'扩充密集交汇与集装箱船样本',51),(375,'开展多摄像头长时间运行和\n端到端延迟测试',88),(472,'结合船舶操纵与桥梁防撞知识\n完善风险评价',91),(571,'系统定位为“辅助监管与人工复核支撑”，\n不把模型输出表述为自动执法结论',80)]:
    shape(1107,y+15,15,15,RED,None,'oval');text(t,1145,y,483,h,30)
# The bridge artwork is a bounded footer region. Text above it remains native.
crop('closing-bridge-footer',0,776,1672,165)
line(492,722,679,722,RED,.8);line(994,722,1180,722,RED,.8)
text('谢 谢',729,672,221,104,82,True,RED,align='center')

out=RUN/'round2';out.mkdir(exist_ok=True)
(out/'measured-plan.json').write_text(json.dumps(deck,ensure_ascii=False,indent=2),encoding='utf-8')
manifest={'scope':'visible text measured and transcribed from the frozen ImageGen masters; full source narration retained in speaker notes','slides':[{'slide_id':s['slide_id'],'exact_text':[t['text'] for t in s['texts']]} for s in deck['slides']]}
(out/'visible-text-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'slides':len(deck['slides']),'texts':sum(len(s['texts']) for s in deck['slides']),'shapes':sum(len(s['shapes']) for s in deck['slides']),'plan':str(out/'measured-plan.json')},ensure_ascii=False))
