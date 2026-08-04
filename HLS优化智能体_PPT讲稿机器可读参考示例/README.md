# HLS 优化智能体 PPT＋讲稿机器可读参考示例

这是一个可直接作为 PPT 生成 Agent reference 的自包含参考包。它将原始 PPT、逐页渲染、页面结构、可见文字、逐页讲稿、叙事角色、视觉规则和质量提示放在同一目录中。

## 推荐读取顺序

1. `manifest.json`
2. `AGENT_PROMPT.md`
3. `narrative/slide-map.json`
4. `narrative/speaker-script.json`
5. `style/style-guide.md`
6. `qa/source-quality-notes.md`
7. 按需要读取 `renders/`、`slides/slide-content.json` 与 `structure/layouts/`

## 关键文件

- `deck/reference-deck.pptx`：保留母版和可编辑结构的主参考 PPT。
- `deck/source-speaker-script.docx`：原始讲稿。
- `renders/slide-001.png` 至 `slide-010.png`：每页视觉参考。
- `narrative/speaker-script.json`：讲稿逐页对齐、规范化修改记录及估算时长。
- `narrative/slide-map.json`：页面角色、结论、版式、检索关键词及复用边界。
- `slides/slide-content.json`：逐页可见文字、对象编号和嵌入备注。
- `structure/layouts/`：逐页元素坐标、类型、字体与样式结构。
- `assets/source-media/`：从源 PPT 提取的原始媒体资源。
- `qa/source-quality-notes.md`：源文件中不应被机械复制的问题。

## 参考模式

- 视觉模板：严格参考，可复制源页并编辑继承元素。
- 叙事结构：参考逻辑和节奏，不复制具体事实。
- 讲稿风格：参考解释深度、术语使用和转场。
- 业务数据：默认禁止复用，必须针对新任务重新核验。

全部 Markdown、JSON 文件均采用 UTF-8 编码。
