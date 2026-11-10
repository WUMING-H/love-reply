#!/usr/bin/env python3
"""恋爱档案：两份——「她是谁」和「我是谁、我要什么」。

对她的（按关系槽位，每段关系一份）：
    init / add / list / search / brief / check-promise / stale / accept / forget / export / stats

对自己的（全局唯一，不随对象变）：
    self init / self add / self list / self forget

关系目标（按槽位，决定长期方向，优先级高于单条话术）：
    goal add / goal list / goal done / goal drop

守门：
    guard          检查候选是否踩到自己的底线、短板、硬目标，以及有没有落进具体细节

存储位置：%LOVE_REPLY_HOME%，未设置时用本 Skill 目录下的 data/
    data/profile/{slot}.json   对她的档案 + 关系目标
    data/self.json             自我档案
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

KINDS = ("fact", "read", "unknown", "landmine", "soother", "promise", "event")
PREFIX = {
    "fact": "f", "read": "r", "unknown": "u", "landmine": "l",
    "soother": "s", "promise": "p", "event": "t",
}
LABEL = {
    "fact": "事实", "read": "认知", "unknown": "未知", "landmine": "雷区",
    "soother": "安抚器", "promise": "承诺", "event": "事件",
}
KEY = {
    "fact": "facts", "read": "reads", "unknown": "unknowns", "landmine": "landmines",
    "soother": "soothers", "promise": "promises", "event": "timeline",
}
# 检索权重：雷区与承诺最影响候选，权重最高
WEIGHT = {
    "landmine": 1.6, "promise": 1.4, "soother": 1.3,
    "fact": 1.2, "read": 1.0, "event": 0.9, "unknown": 0.7,
}
CONFIDENCE = ("high", "mid", "low")

BRIEF_MAX_CHARS = 380
BRIEF_ITEM_CHARS = 34
BRIEF_MAX_ITEMS = 6

# 合并后的总预算。自我段单独封顶，避免「我」把「她」挤出去。
BRIEF_TOTAL_CHARS = 520
BRIEF_SELF_CHARS = 170

# ---------------------------------------------------------------- 自我档案

SELF_KINDS = ("trait", "flaw", "limit", "capacity", "value", "voice")
SELF_PREFIX = {"trait": "t", "flaw": "f", "limit": "m",
               "capacity": "c", "value": "v", "voice": "o"}
SELF_LABEL = {"trait": "我", "flaw": "短板", "limit": "底线",
              "capacity": "能兑现", "value": "看重", "voice": "说话"}
# 只有这三类会直接拦截候选文本
SELF_GUARDING = ("limit", "flaw")

# ---------------------------------------------------------------- 关系目标

GOAL_KINDS = ("advance", "hold", "repair", "exit", "understand")
GOAL_LABEL = {"advance": "推进", "hold": "稳住", "repair": "修复",
              "exit": "收尾", "understand": "看清"}
HORIZONS = ("now", "season", "long")
HORIZON_LABEL = {"now": "这次", "season": "本阶段", "long": "长期"}

# ---------------------------------------------------------------- 阶段闸门

# 每个阶段允许、有条件允许、禁止的策略。allow/deny 是硬闸门，
# conditional 表示「可以，但要满足该阶段的前置条件」。
# detail 是细节密度：一句话里该给多少具体信息。
# 修复期细节要求低不是为了省事——细节在修复期会被当成辩解材料。
STAGE = {
    "stranger": {
        "task": "让她愿意继续回你，不提任何要求",
        "allow": ["minimal", "care"],
        "conditional": ["substantive"],
        "deny": ["advance", "repair", "hold"],
        "detail": "低", "max_chars": 24,
        "trap": "自我介绍式长段、查户口、连发追问、过早表态",
    },
    "warming": {
        "task": "把「有来有回」变成「见过面」，只推半步",
        "allow": ["minimal", "care", "substantive"],
        "conditional": ["advance"],
        "deny": ["repair", "hold"],
        # 「只推半步」的机械判据：邀约必须带退路，否则她拒绝的成本太高
        "advance_softener": ("有空", "方便", "要是", "如果", "不想", "看你想",
                             "随你", "不勉强", "看情况"),
        "detail": "中", "max_chars": 34,
        "trap": "把闲聊当信号、一次性推太满、给方案却没给退路",
    },
    "dating": {
        "task": "确认她愿不愿意继续，节奏由她定",
        "allow": ["minimal", "substantive", "advance"],
        "conditional": ["care", "repair"],
        "deny": ["hold"],
        "detail": "中高", "max_chars": 40,
        "trap": "用下一次邀约测试她、把不确定说成确定、过度解读已读不回",
    },
    "couple_early": {
        "task": "把磨合期的分歧说清楚，不攒着",
        "allow": ["minimal", "substantive", "advance", "care", "repair"],
        "conditional": ["hold"],
        "deny": [],
        "detail": "高", "max_chars": 60,
        "trap": "为了不吵而回避、翻旧账、用分手当筹码",
    },
    "couple_stable": {
        "task": "维持日常，把注意力放在她说过的事上",
        "allow": ["minimal", "substantive", "care", "repair", "hold"],
        "conditional": ["advance"],
        "deny": [],
        "detail": "高", "max_chars": 60,
        "trap": "只回情绪不接具体事、把稳定当成不用经营、仪式感替代日常",
    },
    "repairing": {
        "task": "先让她确认你听懂了，再谈事实",
        "allow": ["hold", "repair", "minimal", "care"],
        "conditional": ["substantive"],
        "deny": ["advance"],
        "detail": "低", "max_chars": 34,
        "trap": "解释动机、罗列细节自证、追加新承诺、逼她当场表态",
    },
}


# ---------------------------------------------------------------- 存储

def home() -> Path:
    env = os.environ.get("LOVE_REPLY_HOME")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent.parent / "data"


def profile_path(slot: str) -> Path:
    return home() / "profile" / f"{slot}.json"


def self_path() -> Path:
    return home() / "self.json"


def empty(slot: str) -> dict:
    return {
        "slot": slot,
        "version": 1,
        "updated_at": now(),
        "person": {"alias": "她", "stage": "warming", "since": "", "basics": {}},
        "facts": [], "reads": [], "unknowns": [],
        "landmines": [], "soothers": [], "promises": [], "timeline": [],
        "goals": [],
    }


def empty_self() -> dict:
    return {"version": 1, "updated_at": now(), "person": {"alias": "我"},
            "items": []}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> date:
    return date.today()


def load(slot: str) -> dict:
    p = profile_path(slot)
    if not p.exists():
        raise SystemExit(f"档案不存在：{p}\n先跑 init。")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"档案 JSON 损坏：{p}（{exc}）")


def save(slot: str, data: dict) -> Path:
    p = profile_path(slot)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def load_self(required: bool = False) -> dict | None:
    p = self_path()
    if not p.exists():
        if required:
            raise SystemExit(f"自我档案不存在：{p}\n先跑 self init。")
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"自我档案 JSON 损坏：{p}（{exc}）")


def save_self(data: dict) -> Path:
    p = self_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = now()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def next_id(data: dict, kind: str) -> str:
    bucket = data[KEY[kind]]
    prefix = PREFIX[kind]
    nums = [int(x["id"][len(prefix):]) for x in bucket
            if x.get("id", "").startswith(prefix) and x["id"][len(prefix):].isdigit()]
    return f"{prefix}{max(nums, default=0) + 1}"


def find(data: dict, item_id: str) -> tuple[str, dict] | tuple[None, None]:
    for kind, key in (("fact", "facts"), ("read", "reads"), ("unknown", "unknowns"),
                      ("landmine", "landmines"), ("soother", "soothers"),
                      ("promise", "promises"), ("event", "timeline")):
        for item in data.get(key, []):
            if item.get("id") == item_id:
                return key, item
    return None, None


# ---------------------------------------------------------------- 检索

PUNCT = re.compile(r"[\s，。！？、；：「」『』（）()\[\]…—~,.!?;:\"'“”‘’]+")

# 只过滤纯功能字。像「说」「累」「钱」这类，字面重叠就是真信号，不能当停用字删掉。
STOP_CHARS = set("的了呢吧吗啊呀哦嗯是我你他她它们这那有就都也还在和与把被给对很太不没要会能着过")


def content_chars(text: str) -> set[str]:
    s = PUNCT.sub("", text)
    return {c for c in s if c not in STOP_CHARS}


def bigrams(text: str) -> set[str]:
    s = PUNCT.sub("", text)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


# 低于这个分数视为不相关。宁可少给，也不要把「生日」塞进「她说累」的上下文里。
MIN_SCORE = 0.15


def score_entry(query: str, text: str, tag: str, weight: float) -> float:
    """字级相似度为主、双字词为辅。

    纯双字重叠会把「她说今天好累」和「她说生日」判成相关，因为共享「她说」。
    字级 Dice 对实词更敏感，也天然惩罚长度不匹配。
    """
    q = content_chars(query)
    e = content_chars(text + " " + (tag or ""))
    if not q or not e:
        return 0.0
    # 只共享一个字通常是巧合（「她说今天好累」和「她说生日」只共享「她说」），
    # 宁可不给，也不要往上下文里塞噪音。
    if len(q & e) < 2 and len(q) > 1:
        return 0.0
    char_sim = dice(q, e)
    gram_sim = dice(bigrams(query), bigrams(text + " " + (tag or "")))
    return round((0.65 * char_sim + 0.35 * gram_sim) * weight, 4)


def entries(data: dict) -> list[tuple[str, dict, str]]:
    """(kind, item, 检索文本)"""
    out = []
    for item in data.get("facts", []):
        out.append(("fact", item, item["text"]))
    for item in data.get("reads", []):
        out.append(("read", item, f"{item.get('tag', '')} {item['text']}"))
    for item in data.get("landmines", []):
        out.append(("landmine", item, item["text"]))
    for item in data.get("soothers", []):
        out.append(("soother", item, item["text"]))
    for item in data.get("promises", []):
        if item.get("status", "open") == "open":
            out.append(("promise", item, item["text"]))
    for item in data.get("timeline", []):
        out.append(("event", item, item.get("event", "")))
    for item in data.get("unknowns", []):
        out.append(("unknown", item, item["text"]))
    return out


def search(data: dict, query: str, limit: int = 6) -> list[tuple[float, str, dict, str]]:
    scored = []
    for kind, item, text in entries(data):
        s = score_entry(query, text, item.get("tag", ""), WEIGHT.get(kind, 1.0))
        if s >= MIN_SCORE:
            scored.append((round(s, 3), kind, item, text))
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]


# ---------------------------------------------------------------- 命令

def cmd_init(args) -> int:
    p = profile_path(args.slot)
    if p.exists() and not args.force:
        print(json.dumps({"ok": False, "error": f"已存在：{p}，要重建加 --force"},
                         ensure_ascii=False))
        return 1
    data = empty(args.slot)
    data["person"].update({
        "alias": args.alias or "她",
        "stage": args.stage or "warming",
        "since": args.since or "",
    })
    path = save(args.slot, data)
    print(json.dumps({"ok": True, "written": str(path), "slot": args.slot,
                      "next": "用 add 录入事实、对她的认知、雷区与承诺"},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_add(args) -> int:
    data = load(args.slot)
    kind = args.kind
    if kind not in KINDS:
        print(json.dumps({"ok": False, "error": f"kind 必须是 {KINDS}"}, ensure_ascii=False))
        return 1

    text = args.text.strip()
    if not text:
        print(json.dumps({"ok": False, "error": "text 不能为空"}, ensure_ascii=False))
        return 1

    warnings: list[str] = []
    item = {"id": next_id(data, kind), "text": text, "added": today().isoformat()}

    if kind == "fact":
        item["source"] = args.source or "未标注"
        item["date"] = args.date or ""
        data["facts"].append(item)
    elif kind == "read":
        item["confidence"] = args.confidence if args.confidence in CONFIDENCE else "mid"
        item["evidence"] = args.evidence or ""
        item["tag"] = args.tag or ""
        item["checked"] = today().isoformat()
        same_tag = [r for r in data["reads"]
                    if item["tag"] and r.get("tag") == item["tag"] and r["text"] != text]
        if same_tag:
            warnings.append(
                "已有同主题认知：" + "；".join(r["text"][:24] for r in same_tag[:2])
                + "。若已改变，先 forget 旧条目，否则会互相干扰。")
        if item["confidence"] == "high" and not item["evidence"]:
            warnings.append("标了 high 但没写证据，建议补 --evidence（否则按 mid 用更安全）")
        data["reads"].append(item)
    elif kind == "unknown":
        data["unknowns"].append(item)
    elif kind == "landmine":
        data["landmines"].append(item)
    elif kind == "soother":
        data["soothers"].append(item)
    elif kind == "promise":
        item["due"] = args.due or ""
        item["status"] = "open"
        data["promises"].append(item)
    elif kind == "event":
        item["date"] = args.date or today().isoformat()
        data["timeline"].append({"id": item["id"], "event": text, "date": item["date"],
                                 "added": item["added"]})
        item = data["timeline"][-1]

    path = save(args.slot, data)
    print(json.dumps({"ok": True, "written": str(path), "kind": kind, "item": item,
                      "warnings": warnings}, ensure_ascii=False, indent=2))
    return 0


def cmd_list(args) -> int:
    data = load(args.slot)
    kinds = [args.kind] if args.kind else list(KINDS)
    out = {}
    for kind in kinds:
        out[kind] = data.get(KEY[kind], [])
    print(json.dumps({"slot": args.slot, "person": data.get("person"), "items": out},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_search(args) -> int:
    data = load(args.slot)
    hits = search(data, args.query, args.limit)
    print(json.dumps({
        "query": args.query,
        "hits": [{"score": s, "kind": k, "id": it.get("id"), "text": t,
                  **({"confidence": it["confidence"]} if k == "read" else {}),
                  **({"due": it["due"]} if k == "promise" else {})}
                 for s, k, it, t in hits],
    }, ensure_ascii=False, indent=2))
    return 0


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


def cmd_brief(args) -> int:
    """给模型看的注入摘要。必须短——它进的是每次调用的上下文。"""
    data = load(args.slot)
    person = data.get("person", {})
    head = f"[{person.get('alias', '她')}·{person.get('stage', '未知阶段')}"
    if person.get("since"):
        head += f"·自{person['since']}"
    head += "]"

    picked: list[tuple[str, dict, str]] = []
    seen: set[str] = set()

    def push(kind: str, item: dict, text: str) -> None:
        if item.get("id") in seen or len(picked) >= BRIEF_MAX_ITEMS:
            return
        seen.add(item.get("id"))
        picked.append((kind, item, text))

    # 1 与当前对话相关的
    if args.query:
        for _, kind, item, text in search(data, args.query, BRIEF_MAX_ITEMS):
            # 检索文本里混了 tag，展示用原文
            push(kind, item, item.get("text") or item.get("event") or text)

    # 2 全局必带：雷区、有效的安抚方式
    for kind, key in (("landmine", "landmines"), ("soother", "soothers")):
        for item in data.get(key, [])[:2]:
            push(kind, item, item["text"])

    # 3 未兑现且临近/逾期的承诺
    for item in sorted(data.get("promises", []), key=lambda x: x.get("due") or "9999"):
        if item.get("status", "open") != "open":
            continue
        due = item.get("due") or ""
        if not due or due <= (today() + timedelta(days=14)).isoformat():
            push("promise", item, item["text"])

    # 4 兜底：什么都没命中时，带最近的事实和认知，总比空手好
    if not picked:
        for item in reversed(data.get("facts", [])):
            push("fact", item, item["text"])
            if len(picked) >= 3:
                break
        for item in reversed(data.get("reads", [])):
            push("read", item, item["text"])
            if len(picked) >= 5:
                break

    # 「我」这一段先算出来：它既进摘要，也决定空档案时要不还是要输出
    sd = load_self()
    me = self_block(sd, data.get("goals", []), BRIEF_SELF_CHARS)

    if not picked and not me:
        print(head + "\n（档案里还没有内容，先录入几条事实和雷区）")
        return 0

    lines: list[str] = []

    # 0 先放「我」：目标决定方向，底线决定禁区。没有自我档案就整段跳过。
    if me:
        lines.append("[我]")
        lines.extend(me)

    # 1 再放「她」
    lines.append(head)
    used = sum(len(x) + 1 for x in lines)
    if person.get("stage") in STAGE:
        task = f"任务 {STAGE[person['stage']]['task']}"
        if used + len(task) + 1 <= BRIEF_TOTAL_CHARS:
            lines.append(task)
            used += len(task) + 1
    for kind, item, text in picked:
        line = brief_line(kind, text, item)
        if used + len(line) + 1 > BRIEF_TOTAL_CHARS:
            break
        lines.append(line)
        used += len(line) + 1

    stale_count = sum(1 for r in data.get("reads", []) if is_stale(r, args.stale_days))
    if stale_count and used + 24 < BRIEF_TOTAL_CHARS:
        lines.append(f"（{stale_count} 条认知超过 {args.stale_days} 天未复核）")

    print("\n".join(lines))
    return 0


def is_stale(item: dict, days: int) -> bool:
    checked = item.get("checked") or item.get("added") or ""
    if not checked:
        return True
    try:
        return (today() - date.fromisoformat(checked[:10])).days >= days
    except ValueError:
        return True


def cmd_check_promise(args) -> int:
    data = load(args.slot)
    horizon = today() + timedelta(days=args.within)
    rows = []
    for item in data.get("promises", []):
        if item.get("status", "open") != "open":
            continue
        due = item.get("due") or ""
        overdue = bool(due) and due < today().isoformat()
        soon = bool(due) and not overdue and due <= horizon.isoformat()
        if overdue or soon or not due:
            rows.append({
                "id": item["id"], "text": item["text"], "due": due or None,
                "state": "逾期" if overdue else ("临近" if soon else "无期限"),
            })
    order = {"逾期": 0, "临近": 1, "无期限": 2}
    rows.sort(key=lambda r: (order[r["state"]], r["due"] or "9999"))
    print(json.dumps({"slot": args.slot, "count": len(rows), "promises": rows},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_stale(args) -> int:
    data = load(args.slot)
    rows = [{"id": r["id"], "text": r["text"], "confidence": r.get("confidence"),
             "checked": r.get("checked") or r.get("added")}
            for r in data.get("reads", []) if is_stale(r, args.days)]
    print(json.dumps({"slot": args.slot, "days": args.days, "count": len(rows),
                      "reads": rows}, ensure_ascii=False, indent=2))
    return 0


def cmd_accept(args) -> int:
    data = load(args.slot)
    changed = []
    for item_id in args.ids:
        key, item = find(data, item_id)
        if item is None:
            continue
        if key == "reads":
            item["checked"] = today().isoformat()
            changed.append(item_id)
        elif key == "promises":
            item["status"] = "done"
            changed.append(item_id)
    if changed:
        save(args.slot, data)
    print(json.dumps({"ok": bool(changed), "confirmed": changed}, ensure_ascii=False))
    return 0 if changed else 1


def cmd_forget(args) -> int:
    data = load(args.slot)
    removed = []
    for item_id in args.ids:
        key, item = find(data, item_id)
        if item is None:
            continue
        data[key].remove(item)
        removed.append({"id": item_id, "kind": key})
    if removed:
        save(args.slot, data)
    print(json.dumps({"ok": bool(removed), "removed": removed}, ensure_ascii=False))
    return 0 if removed else 1


def cmd_export(args) -> int:
    data = load(args.slot)
    person = data.get("person", {})
    out = [f"# 档案 · {person.get('alias', '她')}", ""]
    meta = [f"阶段：{person.get('stage', '')}"]
    if person.get("since"):
        meta.append(f"开始：{person['since']}")
    out.append("　".join(meta))
    out.append("")

    def block(title: str, key: str, fmt) -> None:
        items = data.get(key, [])
        if not items:
            return
        out.append(f"## {title}")
        for it in items:
            out.append(f"- {fmt(it)}")
        out.append("")

    def fmt_fact(it: dict) -> str:
        bits = []
        if it.get("source"):
            bits.append(f"来源：{it['source']}")
        if it.get("date"):
            bits.append(it["date"])
        return it["text"] + (f"（{'，'.join(bits)}）" if bits else "")

    block("事实（可核验）", "facts", fmt_fact)
    block("我对她的认知", "reads",
          lambda it: f"{it['text']}（置信：{it.get('confidence', 'mid')}"
                     f"{'，证据：' + it['evidence'] if it.get('evidence') else ''}）")
    block("还不知道的", "unknowns", lambda it: it["text"])
    block("雷区", "landmines", lambda it: it["text"])
    block("有效的安抚方式", "soothers", lambda it: it["text"])
    block("承诺", "promises",
          lambda it: f"{it['text']}（{it.get('due') or '无期限'}，{it.get('status', 'open')}）")
    block("时间线", "timeline", lambda it: f"{it.get('date', '')} {it.get('event', '')}")

    goals = data.get("goals", [])
    if goals:
        out.append("## 关系目标")
        for g in goals:
            flag = "［硬］" if g.get("hard") else ""
            out.append(f"- {flag}{g['text']}（{HORIZON_LABEL.get(g.get('horizon'), '')}"
                       f"·{GOAL_LABEL.get(g.get('kind'), '')}·{g.get('status', 'active')}）")
        out.append("")

    text = "\n".join(out)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(json.dumps({"ok": True, "written": args.out}, ensure_ascii=False))
    else:
        print(text)
    return 0


def cmd_stats(args) -> int:
    data = load(args.slot)
    counts = {k: len(data.get(v, [])) for k, v in (
        ("fact", "facts"), ("read", "reads"), ("unknown", "unknowns"),
        ("landmine", "landmines"), ("soother", "soothers"),
        ("promise", "promises"), ("event", "timeline"))}
    open_promises = sum(1 for p in data.get("promises", [])
                        if p.get("status", "open") == "open")
    low = sum(1 for r in data.get("reads", []) if r.get("confidence") == "low")
    stale = sum(1 for r in data.get("reads", []) if is_stale(r, args.stale_days))
    sd = load_self()
    print(json.dumps({
        "slot": args.slot, "counts": counts, "open_promises": open_promises,
        "low_confidence_reads": low, "stale_reads": stale,
        "stage": data.get("person", {}).get("stage"),
        "active_goals": sum(1 for g in data.get("goals", []) if g.get("status") == "active"),
        "self_items": len((sd or {}).get("items", [])),
        "path": str(profile_path(args.slot)),
    }, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- 自我档案

def self_id(items: list[dict], kind: str) -> str:
    p = SELF_PREFIX[kind]
    nums = [int(i["id"][len(p):]) for i in items
            if i.get("id", "").startswith(p) and i["id"][len(p):].isdigit()]
    return f"{p}{max(nums, default=0) + 1}"


def cmd_self_init(args) -> int:
    p = self_path()
    if p.exists() and not args.force:
        print(json.dumps({"ok": False, "error": f"已存在：{p}，要重建加 --force"},
                         ensure_ascii=False))
        return 1
    data = empty_self()
    data["person"]["alias"] = args.alias or "我"
    path = save_self(data)
    print(json.dumps({"ok": True, "written": str(path),
                      "next": "用 self add 录入底线、短板、能兑现的范围"},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_self_add(args) -> int:
    data = load_self(required=False) or empty_self()
    kind = args.kind
    if kind not in SELF_KINDS:
        print(json.dumps({"ok": False, "error": f"kind 必须是 {SELF_KINDS}"}, ensure_ascii=False))
        return 1
    text = args.text.strip()
    if not text:
        print(json.dumps({"ok": False, "error": "text 不能为空"}, ensure_ascii=False))
        return 1

    warnings: list[str] = []
    forbid = [w.strip() for w in (args.forbid or []) if w.strip()]
    item = {"id": self_id(data["items"], kind), "kind": kind, "text": text,
            "forbid": forbid, "evidence": args.evidence or "",
            "added": today().isoformat()}

    if kind in SELF_GUARDING and not forbid:
        warnings.append("没配 --forbid，守门无法自动拦截。"
                        "补几个「不该出现在候选里的说法」，例如 --forbid 搬过去 辞职")
    if len(text) < 6:
        warnings.append("太短，多半是标签而不是行为。写成能观察到的样子更有用")
    if kind == "trait" and not item["evidence"]:
        warnings.append("建议补 --evidence 写一个具体行为（「她隔两小时没回我会反复看手机」）")

    same = [i for i in data["items"] if i["kind"] == kind and i["text"] == text]
    if same:
        warnings.append(f"重复条目，已存在 {same[0]['id']}")

    data["items"].append(item)
    path = save_self(data)
    print(json.dumps({"ok": True, "written": str(path), "item": item,
                      "warnings": warnings}, ensure_ascii=False, indent=2))
    return 0


def cmd_self_list(args) -> int:
    data = load_self()
    if data is None:
        print(json.dumps({"ok": False, "error": "还没有自我档案，先跑 self init"},
                         ensure_ascii=False))
        return 1
    kinds = [args.kind] if args.kind else list(SELF_KINDS)
    out = {k: [i for i in data["items"] if i["kind"] == k] for k in kinds}
    print(json.dumps({"items": out, "path": str(self_path())},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_self_forget(args) -> int:
    data = load_self(required=True)
    removed = []
    for item_id in args.ids:
        for item in list(data["items"]):
            if item.get("id") == item_id:
                data["items"].remove(item)
                removed.append(item_id)
    if removed:
        save_self(data)
    print(json.dumps({"ok": bool(removed), "removed": removed}, ensure_ascii=False))
    return 0 if removed else 1


def cmd_self_export(args) -> int:
    data = load_self(required=True)
    out = ["# 自我档案", ""]
    for kind in SELF_KINDS:
        items = [i for i in data["items"] if i["kind"] == kind]
        if not items:
            continue
        out.append(f"## {SELF_LABEL[kind]}")
        for it in items:
            line = f"- {it['text']}"
            if it.get("evidence"):
                line += f"（证据：{it['evidence']}）"
            if it.get("forbid"):
                line += f"［触发词：{'、'.join(it['forbid'])}］"
            out.append(line)
        out.append("")
    text = "\n".join(out)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(json.dumps({"ok": True, "written": args.out}, ensure_ascii=False))
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- 关系目标

def goal_id(goals: list[dict]) -> str:
    nums = [int(g["id"][1:]) for g in goals
            if g.get("id", "").startswith("g") and g["id"][1:].isdigit()]
    return f"g{max(nums, default=0) + 1}"


def cmd_goal_add(args) -> int:
    data = load(args.slot)
    if args.kind not in GOAL_KINDS:
        print(json.dumps({"ok": False, "error": f"kind 必须是 {GOAL_KINDS}"},
                         ensure_ascii=False))
        return 1
    text = args.text.strip()
    if not text:
        print(json.dumps({"ok": False, "error": "text 不能为空"}, ensure_ascii=False))
        return 1

    goals = data.setdefault("goals", [])
    warnings: list[str] = []
    item = {"id": goal_id(goals), "text": text, "kind": args.kind,
            "horizon": args.horizon if args.horizon in HORIZONS else "season",
            "hard": bool(args.hard), "status": "active",
            "forbid": [w.strip() for w in (args.forbid or []) if w.strip()],
            "due": args.due or "", "added": today().isoformat()}

    active = [g for g in goals if g.get("status") == "active"]
    if len(active) >= 4:
        warnings.append("同时有 4 条以上进行中的目标，模型会在它们之间摇摆。"
                        "先 goal done 掉已完成的，或降级成非硬目标")
    if item["hard"] and not item["forbid"]:
        warnings.append("硬目标没配 --forbid，只能靠提示词约束，守门查不出来")

    goals.append(item)
    save(args.slot, data)
    print(json.dumps({"ok": True, "goal": item, "warnings": warnings},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_goal_list(args) -> int:
    data = load(args.slot)
    goals = data.get("goals", [])
    rows = [{"id": g["id"], "kind": g["kind"], "horizon": g["horizon"],
             "hard": g.get("hard", False), "status": g.get("status", "active"),
             "text": g["text"], "forbid": g.get("forbid", []), "due": g.get("due", "")}
            for g in sorted(goals, key=lambda x: (x.get("status") != "active",
                                                  not x.get("hard", False),
                                                  HORIZONS.index(x["horizon"])
                                                  if x.get("horizon") in HORIZONS else 9))]
    print(json.dumps({"slot": args.slot, "count": len(rows), "goals": rows},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_goal_close(args) -> int:
    data = load(args.slot)
    changed = []
    for g in data.get("goals", []):
        if g.get("id") in args.ids:
            g["status"] = args.status
            g["closed"] = today().isoformat()
            changed.append(g["id"])
    if changed:
        save(args.slot, data)
    print(json.dumps({"ok": bool(changed), "changed": changed, "status": args.status},
                     ensure_ascii=False))
    return 0 if changed else 1


# ---------------------------------------------------------------- 阶段

def stage_card(name: str) -> dict:
    key = (name or "").strip()
    if key not in STAGE:
        raise SystemExit(f"未知阶段：{key}\n可选：{'、'.join(STAGE)}")
    return {"stage": key, **STAGE[key]}


def cmd_stage(args) -> int:
    name = args.name
    if not name:
        data = load(args.slot)
        name = data.get("person", {}).get("stage", "warming")
    print(json.dumps(stage_card(name), ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- 守门

def content_bigrams(text: str) -> set[str]:
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
          strategy: str = "", stage: str = "") -> dict:
    problems: list[str] = []
    notes: list[str] = []

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

    return {"ok": not problems, "problems": problems, "notes": notes,
            "anchors": anchors,
            "stage": stage or None, "strategy": strategy or None}


def cmd_guard(args) -> int:
    self_data = load_self()
    slot_data = load(args.slot) if profile_path(args.slot).exists() else None
    stage = args.stage
    if not stage and slot_data:
        stage = slot_data.get("person", {}).get("stage", "")
    result = guard(args.text, self_data, slot_data, args.strategy, stage)
    if stage:
        card = stage_card(stage)
        result["stage_task"] = card["task"]
        result["stage_trap"] = card["trap"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="恋爱档案")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def slot_arg(p):
        p.add_argument("--slot", default="couple_early")

    p = sub.add_parser("init", help="建立档案")
    slot_arg(p)
    p.add_argument("--alias", default="她")
    p.add_argument("--stage", default="warming")
    p.add_argument("--since", default="")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add", help="录入一条")
    slot_arg(p)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--text", required=True)
    p.add_argument("--source", default="")
    p.add_argument("--date", default="")
    p.add_argument("--confidence", default="mid", choices=CONFIDENCE)
    p.add_argument("--evidence", default="")
    p.add_argument("--tag", default="")
    p.add_argument("--due", default="")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="列出")
    slot_arg(p)
    p.add_argument("--kind", choices=KINDS)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="检索")
    slot_arg(p)
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=6)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("brief", help="生成注入摘要")
    slot_arg(p)
    p.add_argument("--query", default="")
    p.add_argument("--stale-days", type=int, default=60)
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("check-promise", help="列出逾期与临近的承诺")
    slot_arg(p)
    p.add_argument("--within", type=int, default=7)
    p.set_defaults(func=cmd_check_promise)

    p = sub.add_parser("stale", help="列出久未复核的认知")
    slot_arg(p)
    p.add_argument("--days", type=int, default=60)
    p.set_defaults(func=cmd_stale)

    p = sub.add_parser("accept", help="确认认知仍成立 / 承诺已完成")
    slot_arg(p)
    p.add_argument("--ids", nargs="+", required=True)
    p.set_defaults(func=cmd_accept)

    p = sub.add_parser("forget", help="删除条目")
    slot_arg(p)
    p.add_argument("--ids", nargs="+", required=True)
    p.set_defaults(func=cmd_forget)

    p = sub.add_parser("export", help="导出 Markdown")
    slot_arg(p)
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("stats", help="统计")
    slot_arg(p)
    p.add_argument("--stale-days", type=int, default=60)
    p.set_defaults(func=cmd_stats)

    # ---- 自我档案
    p = sub.add_parser("self", help="自我档案：我是谁、我的底线与短板")
    ssub = p.add_subparsers(dest="self_cmd", required=True)

    q = ssub.add_parser("init", help="建立自我档案")
    q.add_argument("--alias", default="我")
    q.add_argument("--force", action="store_true")
    q.set_defaults(func=cmd_self_init)

    q = ssub.add_parser("add", help="录入一条自我认知")
    q.add_argument("--kind", required=True, choices=SELF_KINDS)
    q.add_argument("--text", required=True)
    q.add_argument("--forbid", nargs="*", default=[],
                   help="不该出现在候选里的说法，守门用")
    q.add_argument("--evidence", default="")
    q.set_defaults(func=cmd_self_add)

    q = ssub.add_parser("list", help="列出自我档案")
    q.add_argument("--kind", choices=SELF_KINDS)
    q.set_defaults(func=cmd_self_list)

    q = ssub.add_parser("forget", help="删除自我条目")
    q.add_argument("--ids", nargs="+", required=True)
    q.set_defaults(func=cmd_self_forget)

    q = ssub.add_parser("export", help="导出自我档案")
    q.add_argument("--out", default="")
    q.set_defaults(func=cmd_self_export)

    # ---- 关系目标
    p = sub.add_parser("goal", help="关系目标：我要什么、哪些不能碰")
    gsub = p.add_subparsers(dest="goal_cmd", required=True)

    q = gsub.add_parser("add", help="加一条目标")
    slot_arg(q)
    q.add_argument("--kind", required=True, choices=GOAL_KINDS)
    q.add_argument("--text", required=True)
    q.add_argument("--horizon", default="season", choices=HORIZONS)
    q.add_argument("--hard", action="store_true", help="硬目标：不许被话术牺牲")
    q.add_argument("--forbid", nargs="*", default=[])
    q.add_argument("--due", default="")
    q.set_defaults(func=cmd_goal_add)

    q = gsub.add_parser("list", help="列出目标")
    slot_arg(q)
    q.set_defaults(func=cmd_goal_list)

    q = gsub.add_parser("done", help="标记目标已完成")
    slot_arg(q)
    q.add_argument("--ids", nargs="+", required=True)
    q.set_defaults(func=cmd_goal_close, status="done")

    q = gsub.add_parser("drop", help="放弃目标")
    slot_arg(q)
    q.add_argument("--ids", nargs="+", required=True)
    q.set_defaults(func=cmd_goal_close, status="dropped")

    # ---- 阶段与守门
    p = sub.add_parser("stage", help="查看某阶段的允许策略与任务")
    p.add_argument("--name", default="", choices=[""] + list(STAGE))
    slot_arg(p)
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser("guard", help="检查候选是否踩底线、超阶段、缺细节")
    p.add_argument("--text", required=True)
    slot_arg(p)
    p.add_argument("--strategy", default="")
    p.add_argument("--stage", default="", choices=[""] + list(STAGE))
    p.set_defaults(func=cmd_guard)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
