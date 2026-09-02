"""图解生成提示词工程（计划 T2.1.1 / 上游 §3.4 / UI 文档 §3.4 配色约束）。

生成的组件必须：
- 自包含 HTML/SVG/JS，无任何外部资源（无网络、无 CDN、无字体引入）；
- 背景透明、文字/线条用 currentColor（同一组件在浅色小卡与深色剧场都正确着色，UI U-R2）；
- 内容锚定原文段落（引用必须逐字）；
- 加载完成后向 parent 发送 sidenote:ready 消息（沙箱渲染检测约定，T2.2.2）。
"""

from __future__ import annotations

from ..llm.types import ChatMessage

DIAGRAM_SYSTEM = """你是可交互式教学图解工程师。
为给定概念生成一个自包含的 HTML/SVG/JS 小组件，要求：

1. 输出严格为 JSON：
{"componentHtml":"完整 HTML 字符串","summary":"一句话结论",
"citations":[{"paraId":"段落编号","quote":"原文逐字引用"}]}
2. componentHtml 必须完全自包含：单个 HTML 文档，可含内联 <style>/<svg>/<script>；
   禁止任何外部资源（无 <link>/<img src=http…>/fetch/import），禁止 cookie/localStorage。
3. 视觉约束（必须遵守）：
   - html/body 背景透明（不得设置 background 颜色）；
   - 文字、线条、形状统一使用 currentColor（可对局部用 opacity 变化区分层次）；
   - 适合 320×200 到 960×540 两种尺寸下观看（用 viewBox + 百分比布局）。
4. 交互：至少一处动画或可拖动/可点击的交互（用原生 JS，不用外部库）。
5. 内容必须依据给定段落原文讲解概念，citations 引用必须逐字来自原文。
6. 组件加载完成后执行：parent.postMessage({type:"sidenote:ready", hasContent:true}, "*")；
   若初始化失败请执行 parent.postMessage({type:"sidenote:ready", hasContent:false}, "*")。
7. 语气中立，图内不需要出现「辅助理解」标注（由卡片统一渲染）。

只输出 JSON，不要多余文字。"""

DIAGRAM_REPAIR_SYSTEM = """你是修复工程师。上一版组件在沙箱渲染失败（原因见下）。
请修复并重新输出同样格式的 JSON。要求保持全部视觉与内容约束：
自包含、无外部资源、背景透明、currentColor、加载完成后发送 sidenote:ready 消息。
尽量简化：优先纯 SVG，其次少量内联 JS；去掉一切可能出错的复杂特性。只输出 JSON。"""


def diagram_messages(
    concept: str, para_text: str, para_id: str, *, repair: bool = False, fail_reason: str = ""
) -> list[ChatMessage]:
    system = DIAGRAM_REPAIR_SYSTEM if repair else DIAGRAM_SYSTEM
    user = f"概念：{concept}\n【段落内容】（{para_id}）\n{para_text}\n【/段落内容】"
    if repair:
        user = f"失败原因：{fail_reason or '渲染超时/脚本错误'}\n\n" + user
    return [ChatMessage("system", system), ChatMessage("user", user)]


DEGRADE_EXPLAIN_SYSTEM = """你是学术阅读助理。给定概念与段落原文，写一段不超过 120 字的文字讲解，
帮助读者理解该概念。只依据原文，不要编造。直接输出讲解正文。"""
