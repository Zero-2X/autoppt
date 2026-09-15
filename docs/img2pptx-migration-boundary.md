# img2pptx 迁移边界

本仓库只把 img2pptx 迁移为 onlyppt 的后置“可编辑重建引擎”。迁移范围如下：

```text
onlyppt 原有流程（保持不变）
资料理解 → Storyline → Slide Content Spec → Design System → Storyboard
→ Codex 内置 image_gen 整页视觉母版 → Image QA → image-only PPTX

本次新增的后置层
→ Visual Parsing → Component Manifest → Object Router
→ Native Text / Native Shape / SVG Group / Bounded Raster
→ PowerPoint Render → Diff / Text / Semantic QA → Final PPTX
```

## 不得改变的内容

- 前置资料解析、事实/数字真值和叙事结构。
- 既有页面设计约束、风格 profile、整页 ImageGen 提示词和图片版 PPTX 组装。
- 既有 PowerPoint 渲染、溢出、文本、视觉和 deck-level QA 门禁。
- ImageGen 的平台入口：每页只能由 Codex 内置 `image_gen` 生成；仓库只接收、验证和记录结果。

## 允许新增的内容

- `component_manifest.json` 及其 `content_id`、bbox、z-index、路由、置信度和 provenance。
- 将已有 Slide Manifest 文字映射为原生文本框。
- 将简单几何映射为原生 Shape/Connector。
- 将复杂图示作为独立 SVG group 或有边界的 raster asset。
- 对重建结果执行既有 Render → Diff → Repair 和结构/文本/语义审计。

## 硬性禁止

- 用 OCR 改写已有 Slide Manifest 的正文、技术术语、数字或公式。
- 把整页 `full.svg` 或整页截图当作最终 editable PPT。
- 使用 API key、provider SDK、代理、ComfyUI、Stable Diffusion、本地生图命令或 mock 图片替代内置 `image_gen`。
- 因迁移重写 onlyppt 的前置内容理解和设计工作流。
