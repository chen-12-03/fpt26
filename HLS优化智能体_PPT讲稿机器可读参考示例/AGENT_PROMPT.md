# Agent 使用提示词

你将使用本目录作为 PPT 与讲稿的参考包。

1. 首先读取 `manifest.json`、`README.md`、`narrative/slide-map.json`、`narrative/story-structure.md` 和 `style/style-guide.md`。
2. `deck/reference-deck.pptx` 是视觉结构来源。检查全部源页面，根据新任务为每张输出页选择源参考页，并复制源页后编辑原有元素。
3. 保留源 PPT 的母版、版式、字体、字号、行距、边距、对齐、品牌标识和视觉层级。
4. `narrative/speaker-script.json` 是讲稿的机器可读来源；默认使用 `normalized_text`，需要审计时回看 `source_text` 和 `normalization_changes`。
5. `slides/slide-content.json` 提供逐页可见文字和对象编号；`structure/layouts/` 提供元素坐标与样式信息；`renders/` 用于视觉核对。
6. 新任务的事实、数据、受众和内容要求具有最高优先级。不得直接复用本示例的具体结果、模型数据或团队信息。
7. 制作前先输出“新页面 → 源参考页”的映射。内容不适配时应换页型或拆页，不能靠缩小字体硬塞。
8. 阅读 `qa/source-quality-notes.md`，不要复制源文件已有的重叠、越界和裁切问题。
9. 每页生成演讲者备注，包含讲稿、转场和必要的 `[Sources]`。
10. 完成后逐页渲染并按照 `qa/review-checklist.md` 验收。
