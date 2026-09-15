# onlyppt 项目边界

## 保留

本项目只保留生成、重建、审计和发布 PPT 所需的代码：

- `autopptskills/`
- `autosearch/presentation/`
- `autosearch/stage9_ppt/`
- `autosearch/scripts/run_presentation_workflow.py`
- `autosearch/scripts/iterate_presentation_quality.py`
- `skills/imagegen-to-editable-ppt/`
- PPT 相关测试、文档与环境配置

## 排除

不迁移以下内容：

- `autosearch/research/`、`autosearch/llm/`、研究/实验/论文 prompts 与 templates
- `sample/`、`outputs/`、`runs/`、`workspaces/`、`tmp/`、缓存和 Office 临时目录
- 论文写作、投稿、评审、实验执行和研究课题管理代码
- 项目特定的一次性脚本与历史 deck 产物

## 运行约束

PPT 工作流可以读取用户提供的 source materials，但不得把论文制作流程作为运行前置依赖。PPT 项目的输出都放在项目目录的 `final/ppt/`，经验写入 `improvement/`，接受的 PPTX 永不被下一轮覆盖。

