"""命令实现：26 个 cmd_* 函数，每个子命令对应一个。

这些函数被 cli.main 通过 set_defaults(func=...) 注册。它们共享 storage / render /
guard 三层的工具函数，本身不做存储细节。
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from .constants import (
    CONFIDENCE,
    GOAL_KINDS,
    GOAL_LABEL,
    HORIZONS,
    HORIZON_LABEL,
    KINDS,
    KEY,
    LABEL,
    SELF_KINDS,
    SELF_LABEL,
    STAGE,
    DANGER_DENY,
    ROUND_TWO_TEXT_BUDGET,
    CANDIDATE_BUDGET,
    OUTPUT_BUDGET,
    BRIEF_MAX_ITEMS,
    BRIEF_TOTAL_CHARS,
    BRIEF_SELF_CHARS,
    PREFIX,
    SELF_PREFIX,
)
from .storage import (
    empty, empty_self, find, load, load_self, next_id,
    profile_path, save, save_self, search, self_path, today,
)
from .render import brief_line, persona_block, pitfall_block, self_block, stage_block
from .guard import (
    _parse_candidate, branch_hint, guard, habit, pick_slot, read_signal, stage_card,
)


# ---------------------------------------------------------------- 她的档案

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

    from .storage import item_tags
    warnings: list[str] = []
    item = {"id": next_id(data, kind), "text": text, "added": today().isoformat()}
    tags = [t.strip() for t in (getattr(args, "tag", None) or []) if t and t.strip()]
    if tags:
        item["tags"] = tags

    if kind == "fact":
        item["source"] = args.source or "未标注"
        item["date"] = args.date or ""
        if getattr(args, "core", False):
            item["core"] = True
        data["facts"].append(item)
    elif kind == "read":
        item["confidence"] = args.confidence if args.confidence in CONFIDENCE else "mid"
        item["evidence"] = args.evidence or ""
        item["checked"] = today().isoformat()
        same_tag = [r for r in data["reads"]
                    if r["text"] != text and set(tags) & set(item_tags(r))]
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


def cmd_brief(args) -> int:
    """给模型看的注入摘要。必须短——它进的是每次调用的上下文。"""
    data = load(pick_slot(args.slot))
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

    # 1 常驻事实：忌口、生日这类「说了就必须遵守」的，不靠检索撞。
    #   检索是概率，遵守是义务，两者不能共用一条通道。
    for item in data.get("facts", []):
        if item.get("core"):
            push("fact", item, item["text"])

    # 2 与当前对话相关的
    hit = 0
    if args.query:
        for _, kind, item, text in search(data, args.query, BRIEF_MAX_ITEMS):
            # 检索文本里混了 tag，展示用原文
            push(kind, item, item.get("text") or item.get("event") or text)
            hit += 1

    # 3 全局必带：雷区、有效的安抚方式
    for kind, key in (("landmine", "landmines"), ("soother", "soothers")):
        for item in data.get(key, [])[:2]:
            push(kind, item, item["text"])

    # 4 未兑现且临近/逾期的承诺
    for item in sorted(data.get("promises", []), key=lambda x: x.get("due") or "9999"):
        if item.get("status", "open") != "open":
            continue
        due = item.get("due") or ""
        if not due or due <= (today() + timedelta(days=14)).isoformat():
            push("promise", item, item["text"])

    # 5 兜底：检索一条都没命中时，带最近的事实。
    if hit == 0:
        extra = 0
        for item in reversed(data.get("facts", [])):
            if extra >= 2:
                break
            before = len(picked)
            push("fact", item, item["text"])
            if len(picked) > before:
                extra += 1
        for item in reversed(data.get("reads", [])):
            if extra >= 3:
                break
            before = len(picked)
            push("read", item, item["text"])
            if len(picked) > before:
                extra += 1

    # 「我」这一段先算出来：它既进摘要，也决定空档案时要不还是要输出
    sd = load_self()
    me = self_block(sd, data.get("goals", []), BRIEF_SELF_CHARS)

    if not picked and not me:
        print("\n".join([head, *stage_block(person.get("stage", "")),
                         *persona_block(),
                         *pitfall_block(data),
                         "（档案里还没有内容，先录入几条事实和雷区）"]))
        return 0

    lines: list[str] = []

    # 0 先放「我」：目标决定方向，底线决定禁区。没有自我档案就整段跳过。
    if me:
        lines.append("[我]")
        lines.extend(me)

    # 1 再放「她」
    lines.append(head)
    used = sum(len(x) + 1 for x in lines)
    lines.extend(stage_block(person.get("stage", "")))
    if not data.get("landmines"):
        lines.extend(persona_block())
    lines.extend(pitfall_block(data))
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
        if it.get("core"):
            bits.append("常驻")
        if it.get("tags"):
            bits.append("标签：" + "/".join(it["tags"]))
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
    from .constants import SELF_GUARDING
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

def cmd_stage(args) -> int:
    name = args.name
    if not name:
        data = load(args.slot)
        name = data.get("person", {}).get("stage", "warming")
    print(json.dumps(stage_card(name), ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- 守门

def cmd_guard(args) -> int:
    self_data = load_self()
    slot_data = load(args.slot) if profile_path(args.slot).exists() else None
    stage = args.stage
    if not stage and slot_data:
        stage = slot_data.get("person", {}).get("stage", "")
    result = guard(args.text, self_data, slot_data, args.strategy, stage, args.danger)
    if stage:
        card = stage_card(stage)
        result["stage_task"] = card["task"]
        result["stage_trap"] = card["trap"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


def cmd_prefs(args) -> int:
    print(json.dumps(habit(args.slot), ensure_ascii=False, indent=2))
    return 0


def cmd_kb(args) -> int:
    """意图 × 阶段 → 该读的 2–3 篇。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import kb_route

    try:
        out = kb_route.route(args.intent, args.stage or "", args.danger,
                             tuple(args.flag or ()))
    except (KeyError, LookupError) as exc:
        print(json.dumps({"ok": False, "error": str(exc).strip("'")}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_trace(args) -> int:
    """把「判→取→写→过闸」串成一段决策记录，再做一致性校验。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import kb_route

    if args.file:
        rec = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        raw = getattr(args, "json", "") or ""
        if not raw:
            print(json.dumps({"ok": False, "error": "用 --file 给一段决策记录 JSON"}, ensure_ascii=False))
            return 1
        rec = json.loads(raw)

    problems: list[str] = []
    info: list[str] = []

    stage = (rec.get("stage") or "").strip()
    intent = (rec.get("intent") or "").strip()
    danger = rec.get("danger")
    strategies = rec.get("strategies") or []
    kb_files = rec.get("kb_files") or []
    verify = rec.get("verify") or {}

    # 1 阶段必须合法，否则整条闸门都没跑
    if stage:
        if stage not in STAGE:
            problems.append(f"阶段「{stage}」不是六档之一：{'、'.join(STAGE)}")
        else:
            c = STAGE[stage]
            allow = set(c["allow"])
            conditional = set(c.get("conditional", []))
            deny = set(c.get("deny", []))
            for s in strategies:
                if s in deny:
                    problems.append(f"阶段 {stage} 禁止策略 {s}（{c['task']}）")
                elif s in conditional and s not in allow:
                    info.append(f"阶段 {stage} 里 {s} 是条件策略，需要前置，别当无条件可用")
    else:
        problems.append("没判阶段：阶段闸门整条没跑，别当它过了闸")

    # 2 danger ≥ 7 时不许推进/给方案
    if danger is not None and danger >= 7:
        for s in strategies:
            if s in DANGER_DENY:
                problems.append(f"danger={danger} 却给了 {s}，这时候只该稳住（minimal/care）或补救（repair）")

    # 3 取的篇目必须真能被「意图×阶段×danger」路由出来，否则是取错了
    if intent:
        try:
            routed = kb_route.route(intent, stage, danger)
            expected = set(routed["files"])
            got = {f for f in kb_files if f}
            if got:
                stray = got - expected
                if stray:
                    problems.append("取的篇目路由不出来：" + "、".join(sorted(stray)))
                if not (got & expected) and expected:
                    problems.append("取的知识和意图对不上：该读 " + "、".join(sorted(expected)[:2]))
        except (KeyError, LookupError) as exc:
            problems.append(f"意图路由失败：{exc}")
    elif kb_files:
        info.append("没写 intent，无法核对取的篇目是否该读")

    # 4 verify 的结果如果写了，就该和这里一致；不一致说明过闸和记录对不上
    vverdict = verify.get("verdict")
    if vverdict == "pass" and problems:
        problems.append("verify 报 pass，但决策自相矛盾——上面的问题没查出来，别采信这个 pass")

    ok = not problems
    out = {
        "ok": ok,
        "stage": stage or None,
        "intent": intent or None,
        "danger": danger,
        "strategies": strategies,
        "problems": problems,
        "notes": info,
        "checked": ["阶段闸门", "danger 阈值", "知识路由", "过闸一致性"],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_balance(args) -> int:
    """投入对账：只看客观行为，不给她定罪、不给关系下判决。"""
    raw = getattr(args, "json", "") or ""
    if not raw:
        print(json.dumps({"ok": False, "error": "用 --json 给一段行为记录"}, ensure_ascii=False))
        return 1
    try:
        rec = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"JSON 解析失败：{exc}"}, ensure_ascii=False))
        return 1

    KEYS = ("initiate", "give", "emotion", "avoid")
    mine: dict[str, list[str]] = {}
    hers: dict[str, list[str]] = {}
    missing: list[str] = []
    for k in KEYS:
        mv = rec.get("mine", {}).get(k) or []
        hv = rec.get("hers", {}).get(k) or []
        if not isinstance(mv, list) or not isinstance(hv, list):
            print(json.dumps({"ok": False, "error": f"{k} 必须是字符串数组"}, ensure_ascii=False))
            return 1
        mine[k] = mv
        hers[k] = hv
        if not mv and not hv:
            missing.append(k)

    # 计分语义统一为「你的投入 - 她的投入」的净差，正数 = 你多她少。
    score = 0
    detail: list[dict] = []
    for k, label in (("initiate", "主动发起"), ("give", "实际付出"), ("emotion", "情绪投入")):
        d = len(mine[k]) - len(hers[k])
        score += d
        detail.append({"axis": label, "mine": len(mine[k]), "hers": len(hers[k]), "diff": d})
    avd = len(hers["avoid"]) - len(mine["avoid"])
    score += avd
    detail.append({"axis": "回避逃避", "mine": len(mine["avoid"]), "hers": len(hers["avoid"]), "diff": avd})

    if score <= 1:
        tier = "有来有往"
        note = "两边投入大致对等（或她那边更主动）。别用这个命令去挑刺——对等时继续按正常流程走就行。"
    elif score <= 5:
        tier = "你多她少"
        note = "你这边的投入明显多于她。先别急着下「她不在乎」的结论——可能是阶段使然，也可能她投入的方式和你不一样。值得留意，但不必立刻收手。"
    else:
        tier = "几乎单向"
        note = "绝大部分投入来自你这边，她几乎没有实质回应。这是需要正视的事实。继续单方面加码，只会让你越来越累，而她未必因此更投入。该往回收了——先把你的力气和期待收回来，看她会不会主动补一点。"

    out = {
        "ok": True,
        "tier": tier,
        "score": score,
        "detail": detail,
        "note": note,
        "missing": missing or None,
        "checked": ["主动发起", "实际付出", "情绪投入", "回避逃避"],
        "红线": "这里只摆事实，不下「她爱不爱你」「该不该分」的判断；结果不进候选输出。",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_reflect(args) -> int:
    """复盘回流：把「这次产出好不好」记下来，下次别再犯。"""
    raw = getattr(args, "json", "") or ""
    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    if not raw:
        print(json.dumps({"ok": False, "error": "用 --json 或 --file 给一段复盘记录"},
                         ensure_ascii=False))
        return 1
    try:
        rec = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"JSON 解析失败：{exc}"}, ensure_ascii=False))
        return 1

    slot = pick_slot(rec.get("slot") or args.slot or "couple_early")
    trap = (rec.get("trap") or "").strip()
    missed = (rec.get("missed_fact") or "").strip()
    edited = (rec.get("edited") or "").strip()

    actions: list[str] = []
    notes: list[str] = []

    # 1 易错点落档
    if trap:
        data = load(slot)
        pitfalls = data.setdefault("pitfalls", [])
        dup = next((p for p in pitfalls if p.get("text") == trap), None)
        if dup:
            dup["added"] = today().isoformat()
            actions.append(f"易错点已存在，刷新日期：{trap}")
        else:
            pid = f"x{len(pitfalls) + 1}"
            pitfalls.append({"id": pid, "text": trap, "added": today().isoformat()})
            actions.append(f"易错点已落档（{pid}）：{trap}")
        save(slot, data)

    # 2 漏掉的事实：不自动写
    if missed:
        hint = (f"漏掉的事实「{missed}」建议补进档案："
                f"python scripts/profile_tool.py add --slot {slot} --kind fact "
                f"--text \"{missed}\" --tag <类别词>")
        notes.append(hint)
        actions.append(f"已提示补档：{missed}")

    # 3 你改成的：进风格样本
    if edited:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from style_tool import load_card, save_card, SAFE_DEFAULT
        card = load_card(slot) or {"slot": slot, "metrics": SAFE_DEFAULT,
                                   "strategy": {}, "samples": {}}
        scene = (rec.get("scene") or "reflect").strip()
        card.setdefault("samples", {}).setdefault(scene, [])
        entry = edited if not trap else f"{edited}（{trap}）"
        if edited not in card["samples"][scene]:
            card["samples"][scene].append(edited)
            card["samples"][scene] = card["samples"][scene][-20:]
            save_card(slot, card)
            actions.append(f"改写已进样本（{scene}）：{edited}")

    out = {
        "ok": True,
        "slot": slot,
        "actions": actions,
        "notes": notes,
        "recorded": {
            "trap": bool(trap),
            "missed_fact": bool(missed),
            "edited": bool(edited),
        },
        "红线": "只记「模型哪里判断错了」，不给她定罪；不改 danger/阶段闸门；结果不进候选。",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args) -> int:
    """三条候选一次过两道闸门。"""
    import difflib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from style_tool import check as style_check, load_card

    if args.file:
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
        specs = raw if isinstance(raw, list) else raw.get("candidates", [])
        cands = [s if isinstance(s, dict) else _parse_candidate(str(s)) for s in specs]
    else:
        cands = [_parse_candidate(s) for s in (args.candidate or [])]

    if not cands:
        print(json.dumps({"ok": False, "error": "没有候选。用 --candidate 策略:文字，或 --file"}, ensure_ascii=False))
        return 1

    self_data = load_self()
    slot = pick_slot(args.slot)
    slot_data = load(slot) if profile_path(slot).exists() else None
    stage = args.stage or (slot_data or {}).get("person", {}).get("stage", "")
    if stage and stage not in STAGE:
        stage = ""
    card = load_card(slot)

    rows = []
    for i, c in enumerate(cands, 1):
        text = (c.get("text") or "").strip()
        strat = c.get("strategy") or "auto"
        g = guard(text, self_data, slot_data, strat, stage, args.danger)
        s = style_check(text, card, strat)
        problems = g["problems"] + [f"[表达] {p}" for p in s["problems"]]
        notes = list(g["notes"])
        if c.get("note"):
            notes.insert(0, c["note"])
        rows.append({
            "n": i, "strategy": strat, "text": text, "length": len(text),
            "verdict": "pass" if not problems else "fail",
            "problems": problems,
            "notes": notes,
            "anchors": g["anchors"],
            "target_range": s["target_range"],
        })

    group: list[str] = []

    # ---- 续写模式 ----
    then = (getattr(args, "then", None) or "").strip()
    signal = hit = ""
    prev = None
    if then:
        signal, hit = read_signal(then)
        prev = _parse_candidate(args.prev) if getattr(args, "prev", None) else None
        if len(rows) != 1:
            group.append(f"续写只给一句：现在是 {len(rows)} 条。她回了话，这一轮不该再让用户重新挑一次")
        if prev is None:
            group.append("续写没给 --prev：查不了有没有把上一句又说一遍、有没有连着推两次")
        for r in rows:
            if prev:
                if r["strategy"] == prev["strategy"] and r["strategy"] in ("advance", "substantive"):
                    r["problems"].append(
                        f"[续写] 上一轮就是 {prev['strategy']}，她没给新东西，连着推两次只会更像在逼")
                ratio = difflib.SequenceMatcher(None, r["text"], prev["text"]).ratio()
                if ratio >= 0.75:
                    r["problems"].append(f"[续写] 和上一轮那句重合 {ratio:.0%}，等于把话又说了一遍")
            if signal == "withdraw" and r["strategy"] == "advance":
                r["problems"].append(f"[续写] 她那句在收（「{hit}」），这时候推进是往枪口上撞")
            if r["length"] > ROUND_TWO_TEXT_BUDGET:
                r["problems"].append(
                    f"[续写] {r['length']} 字，第二轮一句话就够，写长了她更不想接")
            if r["problems"]:
                r["verdict"] = "fail"

    strats = [r["strategy"] for r in rows]
    dups = sorted({s for s in strats if strats.count(s) > 1})
    if not then and len(rows) > 3:
        group.append(f"{len(rows)} 条候选，输出只要三条，多的删掉")
    if dups:
        group.append(f"策略重复：{'、'.join(dups)}。三条要真的不同，换措辞不算换策略")
    total_chars = sum(r["length"] for r in rows)
    if total_chars > CANDIDATE_BUDGET and not then:
        group.append(f"三条合计 {total_chars} 字，加判断句和结尾会超过 {OUTPUT_BUDGET} 字上限"
                     f"（候选部分只剩 {CANDIDATE_BUDGET} 字），先砍")

    passed = [r for r in rows if r["verdict"] == "pass"]
    if not stage:
        nxt = "阶段闸门没跑：先用 --stage 指定六档之一，或跑 brief 看档案里写的是哪个。别当它过了闸"
        code = 2
    elif len(passed) != len(rows):
        base = ("没过的按 problems 改，别换策略重写" if passed else
                "一条都没过：先看策略是不是被这一阶段禁了，别硬改文字")
        nxt = base + ("；这组另外还不合格：" + "；".join(group) if group else "")
        code = 2
    elif group:
        nxt = ("这一条过闸了，但还不能发：" if then else "三条都过闸了，但这组还不合格：") + "；".join(group)
        code = 2
    else:
        nxt = "可以直接输出"
        code = 0

    out = {
        "stage": stage or None,
        "stage_gate": "ran" if stage else "skipped",
        "slot": slot,
        "danger": args.danger,
        "has_style_card": card is not None,
        "candidates": rows,
        "group_problems": group,
        "total_chars": total_chars,
        "candidate_budget": CANDIDATE_BUDGET,
        "summary": {
            "pass": len(passed), "fail": len(rows) - len(passed),
            "next": nxt,
        },
    }
    if then:
        out["round"] = 2
        out["then"] = then
        out["signal"] = signal
        if hit:
            out["signal_hit"] = hit
        out["prev"] = prev
        out["branch"] = branch_hint(signal)
        out["text_budget"] = ROUND_TWO_TEXT_BUDGET
    if stage:
        out["stage_task"] = stage_card(stage)["task"]
        out["stage_trap"] = stage_card(stage)["trap"]
    h = habit(slot)
    if h["hint"]:
        out["habit"] = h["hint"]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code
