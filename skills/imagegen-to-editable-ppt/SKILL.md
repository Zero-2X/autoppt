---
name: imagegen-to-editable-ppt
description: Reconstruct ImageGen full-slide masters into hybrid editable PPTX using Slide Manifest content truth, Component Manifest routing, native text/shapes, SVG groups, and bounded raster assets.
---

# ImageGen → 可编辑 PPTX 重建引擎

## 迁移边界

本 skill 只迁移 img2pptx 的“视觉解析 → Component Manifest → Object Router
→ 可编辑 PPTX 重建”能力。onlyppt 原有的资料理解、叙事、Slide Spec、Design
System、Storyboard、整页 ImageGen、图片版 PPTX 组装、整套 QA 和发布流程保持不变。
它是后置重建插件，不是新的 PPT 生成器，也不得绕过或重写前置流程。

这个 skill 迁移 img2pptx 的语义分解、组件清单、模块化 SVG、语义审计和
Render → Diff → Repair 思路，但不把整页 `full.svg` 当作最终交付格式。

## 图像生成入口（强制）

每页必须由 Codex 内置 `image_gen` 自动生成一次完整视觉母版，并通过
`builtin_imagegen_handoff.py` 记录 `ig_...` provenance。禁止 API、provider SDK、
代理、本地 ImageGen 命令、ComfyUI/Stable Diffusion 替代服务和 mock 页面。
内置调用失败时只能重试内置 `image_gen` 或停止并写 blocker report。

## 不可变优先级

```text
Slide Manifest（文字/数字/公式真值）
  > reviewed source text
  > OCR（只提议坐标）
ImageGen PNG（视觉母版）
  → component_manifest-v1
  → native_text / native_shape / native_connector / svg_group / raster_asset
```

普通文字必须是原生 PowerPoint 文本框；简单卡片、节点、分隔线和箭头优先
原生 Shape/Connector；复杂科研图保留为独立 SVG group 或有边界的图片资产。
禁止用整页截图伪装成 editable PPT。

## MVP 命令

```powershell
python autopptskills/scripts/reconstruct_imagegen_slide.py `
  <reference.png> <run-dir> `
  --imagegen-manifest <imagegen_manifest.json> `
  --slide-manifest <slide_manifest.json> `
  --force-16x9

python autopptskills/scripts/component_manifest_qa.py `
  <run-dir>/component_manifest.json `
  --json-out <run-dir>/qa/component-manifest-qa.json
```

重建脚本继续输出既有 `deck.json`、`background.png`、`assets/icons`、
`reconstruction-report.json` 和 `editable.pptx`，并新增
`component_manifest.json`。它复用 onlyppt 的 Composer、ImageGen-first gate、
PowerPoint render、exact-text audit、layer contract 和 visual diff gate。

## Component Manifest v1

每个对象包含 `id`、`semantic_type`、`parent_id`、normalized `bbox`、`z_index`、
`content_id`、`render_type`、`style`、`editable`、`confidence` 和 `provenance`。
`content_id` 必须能回溯到 Slide Manifest；`native_text` 没有 content_id 时只能
算 draft/warn，不能作为 gold release。

## QA 规则

- `PPT text == Slide Manifest text`；重要数字、公式和技术名称做 exact match。
- 每页保留 ImageGen provenance，且 semantic full-slide shortcut 为 false。
- 每个组件保留 source bbox 与 routing 结果；低置信度可回退 SVG/raster，但必须记录原因。
- 继续运行现有 `pptx_editability_audit.py`、`pptx_exact_text_audit.py`、
  `layer_contract_gate.py`、`final_visual_gate.py` 和 `release_gate.py`。
