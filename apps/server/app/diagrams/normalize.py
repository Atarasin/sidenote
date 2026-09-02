"""概念规范化（计划 T2.1.3）：同一概念的不同表述归一到同一「概念规范化名」，作为缓存键的一部分。"""

from __future__ import annotations

import re

# 常见同义表述 → 规范名（可按需扩充；规则式，确定性）
_SYNONYMS: dict[str, str] = {
    "供需曲线": "供给与需求曲线",
    "供需均衡": "供给与需求均衡",
    "供给需求曲线": "供给与需求曲线",
    "需求供给曲线": "供给与需求曲线",
    "均衡价格": "市场均衡价格",
    "价格弹性": "需求价格弹性",
    "弹性": "需求价格弹性",
    "边际效用递减": "边际效用递减规律",
    "ppf": "生产可能性边界",
    "gdp": "国内生产总值",
}


def normalize_concept(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[（(].*?[)）]", "", text)  # 去括号注释
    text = text.lower()
    # 只删整段后缀（rstrip 是按字符集删除，会误削「看得见的」这类概念，评审 D12）
    for suffix in ("的概念", "概念"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return _SYNONYMS.get(text, text)
