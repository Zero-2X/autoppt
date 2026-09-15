# 严格可编辑重构工作流

1. 先生成并冻结 39 页 ImageGen 首图，记录源图哈希、逐页文字白名单和 `source_bbox`。
2. 以单张连续背景承载环境纹理；标题、正文、标签、数字全部输出为可见 PowerPoint 原生文本框。
3. 卡片边界、分割线、箭头、节点使用原生形状/连接器；孤立简单图标才可登记 `convertible-vector`。
4. 复杂照片/插画和无法映射稳定字体的书法艺术字只能作为显式 `embedded_text_candidate` / `movable-image` 例外，必须记录理由、源框和布局框。
5. 禁止 `text-raster-fallback`、隐藏 1×1 exact-text proxy、透明文字冒充可编辑性；由 `semantic_editability_gate.py` fail-closed 检查。
6. 每轮都保留独立目录，不覆盖已接受版本；真实 Microsoft PowerPoint 渲染后逐页生成 source/preview/side-by-side/diff heatmap。
7. 只有结构、PowerPoint 渲染、逐页视觉对比、图层审查和人工视觉复核同时通过，才允许进入 release；像素指标不能替代可编辑性或人工审查。

## 当前 round4 例外

Round4 已恢复所有可识别正文/标签为原生文字，删除 round3 的文字裁切和隐藏代理。少量 ImageGen 书法标题仍以 `embedded_text_candidate` 明确登记，并提供同位置原生近似层；这不是“完全路径化”，而是可审计的降级策略。
