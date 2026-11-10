#!/usr/bin/env python3
"""恋爱档案：把「你对她的了解」变成可检索、可复核、可删除的结构化记录。

子命令：
    init           建立一份档案（对象别名、关系阶段、起始时间）
    add            录入一条：事实 / 认知 / 未知 / 雷区 / 安抚器 / 承诺 / 事件
    list           按类型列出
    search         按关键词检索（给回复时用）
    brief          生成注入摘要（受字数预算限制，直接喂给模型）
    check-promise  列出逾期与临近的承诺
    stale          列出太久没复核的认知
    accept         确认某条认知仍然成立（刷新复核日期）
    forget         删除一条
    export         导出为 Markdown（备份或给别人看）
    stats          统计

存储位置：%LOVE_REPLY_HOME%，未设置时用本 Skill 目录下的 data/profile/{slot}.json
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


# ---------------------------------------------------------------- 存储

def home() -> Path:
    env = os.environ.get("LOVE_REPLY_HOME")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent.parent / "data"


def profile_path(slot: str) -> Path:
    return home() / "profile" / f"{slot}.json"


def empty(slot: str) -> dict:
    return {
        "slot": slot,
        "version": 1,
        "updated_at": now(),
        "person": {"alias": "她", "stage": "warming", "since": "", "basics": {}},
        "facts": [], "reads": [], "unknowns": [],
        "landmines": [], "soothers": [], "promises": [], "timeline": [],
    }


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

    if not picked:
        print(head + "\n（档案里还没有内容，先录入几条事实和雷区）")
        return 0

    lines = [head]
    used = len(head)
    for kind, item, text in picked:
        line = brief_line(kind, text, item)
        if used + len(line) + 1 > BRIEF_MAX_CHARS:
            break
        lines.append(line)
        used += len(line) + 1

    stale_count = sum(1 for r in data.get("reads", []) if is_stale(r, args.stale_days))
    if stale_count and used + 24 < BRIEF_MAX_CHARS:
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
    print(json.dumps({
        "slot": args.slot, "counts": counts, "open_promises": open_promises,
        "low_confidence_reads": low, "stale_reads": stale,
        "path": str(profile_path(args.slot)),
    }, ensure_ascii=False, indent=2))
    return 0


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

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
