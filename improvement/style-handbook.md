# PPT 风格与质量手册（持续维护）

## 总体目标

面向高校毕业答辩、论文答辩、比赛答辩和国自然基金申请答辩，优先做到“证据清楚、结论先行、视觉克制但不空、可编辑且可复核”。默认从 `academic_light` 开始：浅色纸面、低饱和海军蓝/青绿色、一个受控强调色、清晰中文层级和与证据绑定的图形。

## 稳定风格原则

- 每页只有一个主结论；标题尽量直接说出结论或回答的问题。
- 先建立阅读路径，再补充次要信息；避免平均分布的卡片墙。
- 非极简页面必须有主证据锚点、明显尺度对比和领域化视觉语言。
- 图表、流程、机制图优先用直接标注解释，不用装饰性图标替代证据。
- 禁止霓虹、赛博 HUD、镜头光晕、无依据 3D、伪 logo、伪奖项、虚构指标、巨型背景图和玻璃拟态。
- 不复制学校 VI、基金官方表单、印章或看似官方的页眉；保留学术可信度但避免“假官方”。

## 高风险失败模式与修复

| 失败模式 | 常见根因 | 首选修复 |
|---|---|---|
| 标题+项目符号，像未完成草稿 | 没有主证据锚点，提示词只描述文字 | 重新写 slide goal；加入一个可读的证据图/流程/对比，并让标题表达结论 |
| 页面过空、像线框 | 过度套用极简风，内容密度不足 | 提高主视觉尺度，加入受控次级证据与解释性标注，不堆装饰 |
| 卡片网格重复 | 组件模板代替叙事 | 改为单一主构图：时间线、因果链、分层剖面、对比图或机制图 |
| 中文乱码/错字 | ImageGen 直接生成长文本 | 缩短可见文字；重要文本走 exact-text whitelist 和 native text；首版乱码则重生成，不局部覆盖母版 |
| 矢量描摹发虚/断线/填充异常 | 复杂图形被强行 SVG 化，路径过多或 PowerPoint 渲染差异 | 降级为 bounded raster；只把简单线稿、边框、箭头和节点转为 native/SVG，并记录拒绝原因 |
| 背景清理留下光晕/残影 | 使用过宽 inpaint mask 或清理了语义边缘 | 使用紧致 source bbox；保留边框/图标/抗锯齿；对照 PowerPoint render 做局部修复 |
| 原生文本与母版重复 | OCR 文字未与背景遮罩或 manifest 对齐 | 依据 reviewed source bbox 删除重复 OCR；重新跑 exact-text 和 visual gate |
| 页面在 PPT 中溢出/换行 | 只看 PNG，没有真实 PowerPoint 渲染 | 每轮都导出真实 PPTX；修正文本框 bbox、字号、行距和安全边界 |
| 数据/指标被“设计”改写 | 视觉稿脱离来源真值 | Slide Manifest > reviewed source > OCR；数字和公式必须来自 whitelist，缺证据就不生成 |

## 可编辑重建取舍

- 普通文字：native PowerPoint text box。
- 简单卡片、线、箭头、节点：native shapes/connectors。
- 简单孤立线稿：仅在 PowerPoint 复核通过后接受 SVG。
- 复杂科研图、照片、界面和图表艺术：bounded movable raster/SVG group。
- 纸张纹理和环境底图：每页一个连续背景；不要平铺 tile。

所有被拒绝的 vector candidate 必须记录 `source_bbox`、`layout_bbox`、拒绝原因和 fallback asset。

## 发布前不可省略的检查

ImageGen provenance、PPTX 可读性、官方溢出检查、exact-text 100%、无替换字符、真实 PowerPoint 导出、逐页视觉复核、连续背景/语义图层审计、所有 rejected vector 记录，以及 release gate 的明确 sign-off。

