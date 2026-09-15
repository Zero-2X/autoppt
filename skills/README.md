# 本项目使用的 Skills

## `autopptskills/SKILL.md`

主技能：ImageGen-first 全页母版、来源真值、可编辑重建、PowerPoint 渲染、视觉/图层/发布门禁。它是本项目默认规范。

## `skills/imagegen-to-editable-ppt/SKILL.md`

后置重建技能：Component Manifest、Object Router、native text/shape、SVG/raster 取舍和 Render → Diff → Repair。它不能绕过主技能，也不能把整页 `full.svg` 当成交付格式。

## 外部 Codex 技能的使用边界

- `imagegen`：仅用于生成完整逐页视觉母版或编辑已有位图；本项目不使用外部图片生成 API/CLI。
- `karpathy-guidelines`：编写/审查工作流代码时采用小步、可验证、低复杂度修改原则。
- `autopptskills`：适用于学术报告、毕业答辩、竞赛答辩、国自然申请答辩和图像转可编辑 PPTX。

实际运行以本目录内的 skill 文件和 `autopptskills/SKILL.md` 为准，避免依赖原研究仓库中的论文/实验技能。

