# onlyppt：独立 PPT 制作工作流

这是从 `autoresearch2ppt` 中抽出的独立 PPT 项目根目录。它只负责“来源材料 → 高校/科研/比赛答辩 PPT”，不包含论文写作、研究课题管理、实验执行、投稿或其他研究流水线。

## 适用场景

- 高等院校毕业答辩、开题/中期/结题答辩
- 学位论文答辩与项目汇报
- 创新创业、学科竞赛、工程项目答辩
- 国家自然科学基金申请答辩/汇报

## 生产主链

```text
source materials
  → source/evidence manifest
  → slide brief + exact-text whitelist
  → one self-contained ImageGen prompt per slide
  → ImageGen full-slide master
  → image-only PPTX
  → semantic editable reconstruction
  → Microsoft PowerPoint render
  → all-slide visual/layer/text/release gates
  → continuous-improvement ledger
```

必须遵守 `autopptskills/SKILL.md` 中的 ImageGen-first、来源真值、语义重建和 Gold release 约束。ImageGen 不可用时保留 prompt/spec 和 blocker report，不用 PIL/SVG/HTML/Canvas 伪造首版整页。

## 快速入口

```powershell
# 结构烟测（不代表视觉交付）
python autosearch/scripts/run_presentation_workflow.py <topic-dir> --mock --presentation-profile thesis_defense

# 真实流程：只接受 Codex 内置 image_gen 输出
python autosearch/scripts/run_presentation_workflow.py <topic-dir> --real --presentation-profile thesis_defense --iterate-quality

# 单页重新生成，保留已接受 deck
python autosearch/scripts/run_presentation_workflow.py <topic-dir> --real --slide-id S03 --presentation-profile thesis_defense
```

`<topic-dir>` 是本项目下的一个 PPT 项目目录，建议至少包含 `source/`、`workspace/stage8_handoff/slide_brief.json`、`workspace/stage8_handoff/ppt_outline.md` 和来源证据文件。脚本会在项目目录内生成 `final/ppt/`、讲稿、验证报告和迭代历史。

## 目录边界

- `autopptskills/`：通用 PPT 技能、风格系统、ImageGen-first、可编辑重建、PowerPoint 渲染和发布门禁。
- `autosearch/presentation/`：仅保留 PPT 所需的来源证据、画像、Slide IR、讲稿和门禁编排。
- `autosearch/ppt/`：逐页提示词、ImageGen 交接、图片版 PPTX 组装与审计。
- `skills/imagegen-to-editable-ppt/`：组件清单和 Object Router 后置重建 skill。
- `tests/`：PPT 工作流和门禁测试。
- `docs/`：PPT 工作流与迁移边界文档。
- `improvement/`：持续改进知识库，记录失败点、矢量化取舍、风格经验和解决办法。

明确不迁入：`autosearch/research`、论文/实验/投稿模板、研究样例、历史输出、缓存、临时目录和与 PPT 无关的根级脚本。

## 持续改进机制

每次生成或质量迭代都应执行：

1. 先读取 `improvement/ppt-improvement-ledger.jsonl` 和 `improvement/style-handbook.md`。
2. 将本次失败点、视觉/矢量问题、根因、修复动作、验证证据写回 ledger。
3. 只接受没有重复已知坏效果、且相对基线没有视觉回退的候选。
4. 将可泛化的修复凝练到 `style-handbook.md`；项目特例只留在项目记录中。

质量迭代器默认读取本目录的 ledger；使用 `--learn` 才会写入全局知识库。
