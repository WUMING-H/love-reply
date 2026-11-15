"""守门与信号判断：候选的底线/阶段/细节拦截，以及续写时的进退判断。

guard 是核心校验入口；read_signal/branch_hint/habit 支撑 verify 的续写模式。
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from pathlib import Path

from .constants import (
    DANGER_DENY,
    EMPTY_MARKS,
    ENGAGED_MARKS,
    PERSONA_HARD,
    PERSONA_SOFT,
    PERSONA_SOFT_HINT,
    SELF_GUARDING,
    SELF_LABEL,
    STRATEGIES,
    WITHDRAW_MARKS,
)
from .storage import home


def stage_card(name: str) -> dict:
    from .constants import STAGE
    key = (name or "").strip()
    if key not in STAGE:
        raise SystemExit(f"未知阶段：{key}\n可选：{'、'.join(STAGE)}")
    return {"stage": key, **STAGE[key]}


def content_bigrams(text: str) -> set[str]:
    from .storage import PUNCT, STOP_CHARS
    s = "".join(c for c in PUNCT.sub("", text) if c not in STOP_CHARS)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def anchors_in(text: str, facts: list[dict]) -> list[str]:
    """候选里有没有真的用上档案中的具体事实。

    判定用连续两字，不是单字重合。用单字时「下午三点……吃饭」会命中
    「她不吃芒果……只喝了两口」（共享「点」「吃」），那是假阳性。
    """
    tb = content_bigrams(text)
    hit = []
    for f in facts:
        if tb & content_bigrams(f.get("text", "")):
            hit.append(f["text"][:26])
    return hit[:3]


def guard(text: str, self_data: dict | None, slot_data: dict | None,
          strategy: str = "", stage: str = "", danger: int | None = None,
          persona: bool = True) -> dict:
    problems: list[str] = []
    notes: list[str] = []

    # 高风险只允许稳住 / 补救 / 留白。这条以前只写在提示词里，代码一个字都不知道，
    # 所以「danger 7 还给了一条约会邀约」永远不可能变红。现在它是参数，可被断言。
    if danger is not None and danger >= 7:
        if strategy in DANGER_DENY:
            problems.append(
                f"[危险 {danger}] 这个程度只允许稳住 / 补救 / 留白，"
                f"不许玩笑、不许 {strategy}。先让人安全，再谈关系")
        elif strategy in ("", "auto"):
            notes.append(f"危险 {danger}：这条按什么策略？没标明就无法确认它是否越线")

    sd = self_data or {}
    for item in sd.get("items", []):
        if item.get("kind") not in SELF_GUARDING:
            continue
        for kw in item.get("forbid", []):
            if kw and kw in text:
                problems.append(
                    f"[{SELF_LABEL.get(item['kind'], item['kind'])} {item['id']}] "
                    f"出现「{kw}」——你写过：{item['text'][:30]}")

    pd = slot_data or {}
    for g in pd.get("goals", []):
        if g.get("status") != "active":
            continue
        for kw in g.get("forbid", []):
            if kw and kw in text:
                problems.append(
                    f"[目标 {g['id']}] 出现「{kw}」——和「{g['text'][:24]}」相冲")

    if stage:
        card = stage_card(stage)
        if strategy and strategy in card["deny"]:
            problems.append(
                f"[阶段 {stage}] 不允许 {strategy}。这一步的任务是：{card['task']}")
        elif strategy and strategy in card["conditional"]:
            notes.append(f"{stage} 阶段允许 {strategy}，但只在前置条件满足时用")
        softeners = card.get("advance_softener") or ()
        if softeners and strategy == "advance" and not any(w in text for w in softeners):
            problems.append(
                f"[阶段 {stage}] 邀约没给退路。这一阶段只推半步，"
                f"加一句「你要是有空」「不想也没关系」这类")
        limit = card.get("max_chars")
        if limit and len(text) > limit:
            problems.append(
                f"[阶段 {stage}] {len(text)} 字，超出该阶段 {limit} 字上限。"
                f"这一阶段细节密度：{card['detail']}")

    anchors = anchors_in(text, pd.get("facts", []))
    if not anchors and strategy in ("substantive", "advance", "repair"):
        notes.append("没接住任何具体事实。这一档候选最好落到她知道的具体东西上")

    # 默认画像的措辞拦截。只影响「怎么说」，不影响 danger。
    # 硬拦：质问反问、催表态——几乎总是错，踩「吃软不吃硬」这条稳定的雷。
    # 软提示：泛夸、讲道理压情绪——偶尔可用，只是对她不是最优。
    if persona:
        for pat, label in PERSONA_HARD:
            if pat.search(text):
                problems.append(f"[画像] {label}——吃软不吃硬，这种话会让她关上")
                break
        for pat, label in PERSONA_SOFT:
            m = pat.search(text)
            if m:
                notes.append(f"[画像] {label}（「{m.group(1)}」）——{PERSONA_SOFT_HINT[label]}")

    return {"ok": not problems, "problems": problems, "notes": notes,
            "anchors": anchors,
            "stage": stage or None, "strategy": strategy or None}


def read_signal(then: str) -> tuple[str, str]:
    """她这一句是进还是退。返回 (信号, 命中的词)。

    只做三档，不求精确：判成退会少说一句，判成进会多说一句。
    宁可少说。
    """
    t = (then or "").strip()
    bare = re.sub(r"[\s，。,.!！?？~～…、]+", "", t)
    for w in WITHDRAW_MARKS:
        if w in bare:
            return "withdraw", w
    # 敷衍必须整句就是那个词，或者同一个字重复（嗯嗯、哦哦）。
    # 用「包含」会把「好呀 那周六怎么样」判成冷淡——一句话里有「好」不代表在敷衍。
    if len(bare) <= 4 and (bare in EMPTY_MARKS or (len(set(bare)) == 1 and bare[0] in "哦嗯好行额噢喔")):
        return "cold", bare
    # 12 字左右就是一句完整的话了，她在给内容，不是敷衍。
    if len(bare) >= 12 or re.search(r"[?？]", t) or any(w in bare for w in ENGAGED_MARKS):
        return "engaged", ""
    return "unclear", ""


def branch_hint(signal: str) -> str:
    return {
        "withdraw": "她已经在往回收了：这条只做收尾，别再提这件事、别再问怎么安排。发完停手，隔一天换个轻松话题，等她主动一次。",
        "cold": "她给得很短：不加码、不追问。这条发完就停，她多给一个字再往下走。",
        "engaged": "她接住了：可以往前一小步，但只走一步，别把下一步也一起说完。",
    }.get(signal, "发完就停。她接了才加温一小步；含糊就隔天换话题；明确拒绝就收线。")


def pick_slot(slot: str) -> str:
    """只有一个档案时就用它。

    默认槽位是 couple_early，但用户常常只建了一份 warming 档案。以前这种情况报
    「档案不存在，先跑 init」，模型很可能顺手再建一份空的——「多份档案先问」的
    噪声就是从这儿来的。读路径上直接收敛到唯一那一份。
    """
    from .storage import profile_path, home
    if profile_path(slot).exists():
        return slot
    d = home() / "profile"
    names = sorted(p.stem for p in d.glob("*.json")) if d.exists() else []
    return names[0] if len(names) == 1 else slot


def _parse_candidate(spec: str) -> dict:
    """`策略:文字` → {strategy, text}。

    三种写法都要认，因为三种都会真实发生：
    - 半角冒号（脚本示例）：`minimal:嗯`
    - 全角冒号（中文输入法默认）：`minimal：嗯`。以前只 partition(":")，
      于是「minimal：」整段被当成正文开头，用户复制就走漏出去了。
    - 策略名拼错：`minmal:嗯`。按相似度归位，别让它继续当正文。
    """
    s = spec.replace("：", ":").replace("﹕", ":")
    head, sep, tail = s.partition(":")
    head = head.strip()
    if sep and head in STRATEGIES + ("auto",):
        return {"strategy": head, "text": tail.strip()}
    if sep and head:
        near = difflib.get_close_matches(head, list(STRATEGIES), n=1, cutoff=0.7)
        if near:
            return {"strategy": near[0], "text": tail.strip(),
                    "note": f"策略名「{head}」不认识，按 {near[0]} 校验"}
        # 长一点的英文前缀多半是想写策略名却没写对。剥掉，别让它跟着候选发出去。
        if len(head) >= 4 and re.fullmatch(r"[A-Za-z_]+", head):
            return {"strategy": "auto", "text": tail.strip(),
                    "note": f"前缀「{head}:」不认识，已剥离，按 auto 校验"}
    return {"strategy": "auto", "text": spec.strip()}


def habit(slot: str) -> dict:
    """从点选记录里统计他偏好的策略。

    这份统计只用于**排序**：同样过闸的三条里先给他常用的那种。它永远不能
    参与准入——「因为你好这口，所以在修复期也给你邀约」正是这套设计要防的事。
    所以只在票数够多时给一句提示，不给分数、不做加权。
    """
    p = home() / "feedback.jsonl"
    if not p.exists():
        return {"n": 0, "hint": ""}
    chosen: Counter = Counter()
    rejected: Counter = Counter()
    n = edited = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("slot") != slot:
            continue
        n += 1
        strat = (row.get("strategy") or "").strip()
        if row.get("kind") == "chosen":
            if strat:
                chosen[strat] += 1
        elif row.get("kind") == "rejected":
            if strat:
                rejected[strat] += 1
        elif row.get("kind") == "edited":
            edited += 1
    out = {"n": n, "chosen": dict(chosen), "rejected": dict(rejected),
           "edited": edited, "hint": ""}
    # 五票以下什么都不说：三次点选里两次选 A，可能是那天只有 A 能用。
    if n < 5 or sum(chosen.values()) < 3:
        return out
    top, cnt = chosen.most_common(1)[0]
    share = cnt / sum(chosen.values())
    if share >= 0.5:
        out["hint"] = f"他以往 {sum(chosen.values())} 次点选里 {cnt} 次是 {top}（{share:.0%}），排序时优先这种；闸门照旧"
    if n >= 5 and edited / n >= 0.4:
        out["hint"] = (out["hint"] + "；" if out["hint"] else "") + \
            f"改写率 {edited / n:.0%}，风格卡可能偏松，建议重新 profile"
    return out
