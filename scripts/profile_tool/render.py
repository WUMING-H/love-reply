"""渲染块：摘要里「我」「阶段」「画像」「易错点」各段的生成。

这些函数把数据格式化成要注入模型上下文的短文本，不写档案、不改状态。
"""
from __future__ import annotations

from .constants import (
    BRIEF_ITEM_CHARS,
    GOAL_LABEL,
    HORIZONS,
    HORIZON_LABEL,
    LABEL,
    SELF_LABEL,
    STAGE,
)


def self_block(sd: dict | None, goals: list[dict], budget: int) -> list[str]:
    """「我是谁、我要什么」那一段。目标排在最前，因为它决定方向。"""
    lines: list[str] = []

    def add(line: str) -> None:
        if sum(len(x) + 1 for x in lines) + len(line) + 1 <= budget:
            lines.append(line)

    active = [g for g in goals if g.get("status") == "active"]
    active.sort(key=lambda g: (not g.get("hard", False),
                               HORIZONS.index(g["horizon"]) if g.get("horizon") in HORIZONS else 9))
    for g in active[:3]:
        flag = "!" if g.get("hard") else ""
        add(f"目标{flag} {g['text']}（{HORIZON_LABEL.get(g.get('horizon'), '本阶段')}·"
            f"{GOAL_LABEL.get(g.get('kind'), g.get('kind'))}）")

    if sd:
        for kind, cap in (("limit", 2), ("flaw", 2), ("capacity", 2), ("value", 1)):
            for item in [i for i in sd.get("items", []) if i.get("kind") == kind][:cap]:
                body = item["text"][:30]
                label = SELF_LABEL[kind]
                # 「看重」这类标签常和句子开头重字，剥掉避免「看重 看重被回应」
                if body.startswith(label):
                    body = body[len(label):].lstrip("：: ")
                add(f"{label} {body}")
    return lines


def brief_line(kind: str, text: str, item: dict) -> str:
    t = text.replace("\n", " ").strip()
    if len(t) > BRIEF_ITEM_CHARS:
        t = t[:BRIEF_ITEM_CHARS] + "…"
    if kind == "read":
        conf = {"high": "高", "mid": "中", "low": "低"}.get(item.get("confidence"), "中")
        flag = "?" if item.get("confidence") == "low" else ""
        return f"认知{flag}[{conf}] {t}"
    if kind == "promise":
        due = item.get("due") or "无期限"
        return f"承诺({due}) {t}"
    if kind == "landmine":
        return f"雷区 {t}"
    if kind == "soother":
        return f"有效 {t}"
    if kind == "fact":
        return f"事实 {t}"
    return f"{LABEL.get(kind, kind)} {t}"


def stage_block(name: str) -> list[str]:
    """阶段卡的三行浓缩。

    以前这一步要单独跑一次 `stage`，那是整条流程里最容易被跳过的一次调用：
    它不给任何跟「她」有关的信息，看起来可以省，而省掉的后果是策略越级。
    并进 brief 之后，取档案就同时拿到了这一阶段允许什么、禁止什么。
    """
    if name not in STAGE:
        return [f"[阶段] 未知「{name}」，先确认是六档里的哪一个：{'、'.join(STAGE)}"]
    c = STAGE[name]
    allow = "/".join(c["allow"])
    if c.get("conditional"):
        allow += "，" + "/".join(c["conditional"]) + " 需前置"
    deny = "/".join(c["deny"]) or "无"
    return [
        f"[阶段 {name}] {c['task']}",
        f"可用 {allow} · 禁 {deny} · ≤{c['max_chars']}字 · 细节{c['detail']}",
        f"忌 {c['trap']}",
    ]


def persona_block() -> list[str]:
    """默认画像的三行浓缩。

    这是「默认先验」，不是档案里的具体事实——它只给沟通方向，不给判断依据。
    档案里一旦写了具体的 landmine / soother，那些优先；这里只在没有档案时兜底。
    三行卡着字数：它和阶段卡一样是固定规则，不占「她」的记忆额度。
    """
    return [
        "[画像] 吃软不吃硬：别质问、别反问、别催她当场表态",
        "[画像] 慢热、要安全感：先接情绪再谈事，先复述她说的再回应",
        "[画像] 泛夸没用：夸具体动作，别「你真好」；她更吃「你注意到了我」",
    ]


def pitfall_block(data: dict) -> list[str]:
    """最近踩过的坑（易错点）的提醒。

    来自 reflect 落档的 trap：模型上一次在这里判断错了，下次别在同一个地方栽跟头。
    只带最近两条，作为提醒不占「她」的记忆额度；它不是判断依据，不改 danger、
    不改阶段闸门，只让模型「这次注意」。空档案时没有。
    """
    pitfalls = data.get("pitfalls", [])
    if not pitfalls:
        return []
    recent = sorted(pitfalls, key=lambda p: p.get("added", ""), reverse=True)[:2]
    return [f"[易错] {p['text']}" for p in recent]
