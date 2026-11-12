"""知识路由：把 references/routes.json 变成一条命令。

以前路由是一张表，模型看表再自己去 Read。表看漏一行、文件名改了、路径写错了，
都不会有人报错——它只是少读一篇，而输出看起来一模一样。
这里把表变成命令：输出就是该读的那 2–3 篇，路径直接可以 Read。

同时兜住三类漂移：声明了但文件不存在、文件存在但没人能到达、路由表与数据不一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "references" / "kb"
ROUTES = ROOT / "references" / "routes.json"
DOC = ROOT / "references" / "routes.md"
BEGIN = "<!-- kb-route:begin -->"
END = "<!-- kb-route:end -->"

_cached: dict | None = None


def load() -> dict:
    global _cached
    if _cached is None:
        _cached = json.loads(ROUTES.read_text(encoding="utf-8"))
    return _cached


def rel(name: str) -> str:
    """路由里写的是 knowledge/xx.md，对外一律给可 Read 的完整相对路径。"""
    return f"references/kb/{name}"


def _match(when: dict, stage: str, danger: int | None) -> bool:
    if "stage" in when:
        if not stage or stage not in when["stage"]:
            return False
    if "danger_min" in when and (danger is None or danger < when["danger_min"]):
        return False
    if "danger_max" in when and (danger is None or danger > when["danger_max"]):
        return False
    return True


def route(intent: str, stage: str = "", danger: int | None = None,
          flags: tuple[str, ...] = ()) -> dict:
    data = load()
    intents = data["intents"]
    if intent not in intents:
        raise KeyError(f"没有这个意图：{intent}。可选：{'、'.join(intents)}")
    spec = intents[intent]

    picked = None
    for row in spec["matrix"]:
        if _match(row.get("when", {}), stage, danger):
            picked = list(row["files"])
            break
    if picked is None:  # 兜底行永远存在，走到这里说明数据坏了
        raise LookupError(f"{intent} 在 stage={stage or '-'} danger={danger} 下没有命中的规则")

    unknown = [f for f in flags if f not in data.get("flags", {})]
    if unknown:
        raise KeyError(f"没有这个 flag：{'、'.join(unknown)}。可选：{'、'.join(data['flags'])}")

    files = picked
    notes = [spec["note"]] if spec.get("note") else []
    applied: list[str] = []
    stop = False
    for name, fl in data.get("flags", {}).items():
        if name not in flags:
            continue
        applied.append(name)
        if fl.get("mode") == "replace":
            files = list(fl["files"])
            stop = bool(fl.get("stop"))
            notes = [fl["note"]] if fl.get("note") else notes
        else:
            files = list(fl["files"]) + files
            if fl.get("note"):
                notes.append(fl["note"])
        if stop:
            # 危机一旦命中，后面的 flag 一律不再叠加：这时候只该有一件事要做
            break

    seen: set[str] = set()
    deduped = []
    for f in files:
        if f not in seen:
            seen.add(f)
            deduped.append(f)

    limit = 1 if stop else int(data.get("max_files", 3))
    capped = len(deduped) > limit
    deduped = deduped[:limit]

    return {
        "intent": intent,
        "intent_label": spec.get("label", ""),
        "stage": stage or None,
        "danger": danger,
        "flags": applied,
        "stop": stop,
        "files": [rel(f) for f in deduped],
        "count": len(deduped),
        "capped": capped,
        "notes": notes,
    }


def _all_declared() -> list[str]:
    data = load()
    out: list[str] = []
    for spec in data["intents"].values():
        for row in spec["matrix"]:
            out.extend(row["files"])
    for fl in data.get("flags", {}).values():
        out.extend(fl["files"])
    return out


def audit() -> dict:
    """三件事：声明的不存在、存在但没人能到、路由表与数据不一致。"""
    data = load()
    on_disk = {str(p.relative_to(KB).as_posix()) for p in KB.rglob("*.md")} if KB.exists() else set()

    declared = set(_all_declared())
    ref_only = {e["file"] for e in data.get("reference_only", [])}
    excluded = {f for group in data.get("exclude", []) for f in group["files"]}

    missing = sorted(declared - on_disk)
    orphans = sorted(on_disk - declared - ref_only - excluded)
    overlap = sorted((declared & excluded) | (declared & ref_only) | (ref_only & excluded))

    dangling_refs = []
    for entry in data.get("reference_only", []):
        doc = ROOT / entry["ref"]
        if not doc.exists():
            dangling_refs.append(f"{entry['file']} 指向不存在的文档 {entry['ref']}")
            continue
        if entry["file"].split("/")[-1] not in doc.read_text(encoding="utf-8"):
            dangling_refs.append(f"{entry['file']} 声称被 {entry['ref']} 引用，但那篇文档里找不到它")

    unreachable_intents = []
    for name, spec in data["intents"].items():
        for stage in ("", "stranger", "warming", "dating", "couple_early",
                      "couple_stable", "repairing"):
            try:
                got = route(name, stage or "", None)["files"]
                if not got:
                    unreachable_intents.append(f"{name} / {stage or '任意阶段'} 没有可读的篇目")
            except LookupError as exc:
                unreachable_intents.append(str(exc))

    return {
        "on_disk": len(on_disk),
        "declared": len(declared),
        "reference_only": len(ref_only),
        "excluded": len(excluded),
        "missing": missing,
        "orphans": orphans,
        "overlap": overlap,
        "dangling_refs": dangling_refs,
        "unreachable_intents": unreachable_intents,
    }


def _when_text(when: dict) -> str:
    parts = []
    if "danger_min" in when and "danger_max" in when:
        parts.append(f"`danger` {when['danger_min']}–{when['danger_max']}")
    elif "danger_min" in when:
        parts.append(f"`danger` ≥ {when['danger_min']}")
    if "stage" in when:
        parts.append("`stage` = " + " / ".join(when["stage"]))
    return " · ".join(parts) or "其他"


def render() -> str:
    data = load()
    lines: list[str] = []
    lines.append(BEGIN)
    lines.append("")
    lines.append("这段由 `scripts/kb_route.py render` 生成，手改会被自检判红。要改路由，改 `references/routes.json`。")
    lines.append("")
    lines.append("按 `intent × stage` 查表，读 **2–3 篇**。路径都在 `references/kb/` 下。"
                 "模型不需要读这张表——跑一次 `python scripts/profile_tool.py kb --intent ...` 直接拿到篇目。")
    lines.append("")
    for name, spec in data["intents"].items():
        lines.append(f"### `intent = {name}`（{spec['label']}）")
        lines.append("")
        lines.append("| 条件 | 读什么 |")
        lines.append("|---|---|")
        for row in spec["matrix"]:
            files = " · ".join(f"`{f}`" for f in row["files"])
            lines.append(f"| {_when_text(row.get('when', {}))} | {files} |")
        lines.append("")
        if spec.get("note"):
            lines.append(f"要点：{spec['note']}")
            lines.append("")

    lines.append("### 特殊情形（`--flag`，优先于主路由）")
    lines.append("")
    lines.append("| flag | 何时用 | 读什么 |")
    lines.append("|---|---|---|")
    for name, fl in data.get("flags", {}).items():
        files = " · ".join(f"`{f}`" for f in fl["files"])
        if fl.get("mode") == "replace":
            files += "（**只读这篇**）"
        lines.append(f"| `{name}` | {fl['applies']} | {files} |")
    lines.append("")
    lines.append("flag 是叠加在 2–3 篇之上的，超过上限时先砍主路由最后一篇——"
                 "特殊情形比通用场景更该被看见。`危机` 是唯一例外：它替换全部，且只读一篇。")
    lines.append("")

    ref_only = data.get("reference_only", [])
    if ref_only:
        lines.append("### 只作为参考入口的篇目")
        lines.append("")
        for entry in ref_only:
            lines.append(f"- `{entry['file']}`：{entry['note']}")
        lines.append("")

    lines.append("### 不参与路由的篇目")
    lines.append("")
    for group in data.get("exclude", []):
        lines.append(f"**{group['reason']}**（{len(group['files'])} 篇）")
        lines.append("")
        lines.append("、".join(f"`{f}`" for f in group["files"]))
        lines.append("")

    lines.append(END)
    return "\n".join(lines) + "\n"


def cmd_render(args) -> int:
    body = render()
    text = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    if args.check:
        if BEGIN not in text or END not in text:
            print("routes.md 里没有生成块标记，无法比对", file=sys.stderr)
            return 1
        current = text[text.index(BEGIN): text.index(END) + len(END)] + "\n"
        if current != body:
            print("routes.md 的生成块与 routes.json 不一致：跑 render 重新生成", file=sys.stderr)
            return 1
        print("routes.md 与 routes.json 一致")
        return 0
    if BEGIN in text and END in text:
        text = text[: text.index(BEGIN)] + body + text[text.index(END) + len(END) + 1:]
    else:
        text = text.rstrip("\n") + "\n\n" + body
    DOC.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    print(f"已写入 {DOC.relative_to(ROOT)}")
    return 0


def cmd_coverage(args) -> int:
    report = audit()
    report["intents"] = list(load()["intents"])
    report["flags"] = list(load().get("flags", {}))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    bad = (report["missing"] or report["orphans"] or report["overlap"]
           or report["dangling_refs"] or report["unreachable_intents"])
    return 1 if bad else 0


def cmd_route(args) -> int:
    try:
        out = route(args.intent, args.stage or "", args.danger, tuple(args.flag or ()))
    except (KeyError, LookupError) as exc:
        print(json.dumps({"ok": False, "error": str(exc).strip("'")}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="知识路由：意图 × 阶段 → 该读的 2–3 篇")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    r = sub.add_parser("route", help="输出该读的篇目")
    r.add_argument("--intent", required=True, choices=list(load()["intents"]))
    r.add_argument("--stage", default="", choices=["", "stranger", "warming", "dating",
                                                  "couple_early", "couple_stable", "repairing"])
    r.add_argument("--danger", type=int, default=None, choices=range(0, 10))
    r.add_argument("--flag", action="append", default=[])
    r.set_defaults(func=cmd_route)

    d = sub.add_parser("render", help="重新生成 routes.md 的表格块")
    d.add_argument("--check", action="store_true", help="只比对，不写入")
    d.set_defaults(func=cmd_render)

    c = sub.add_parser("coverage", help="谁到不了、谁不存在、路由表是否漂移")
    c.set_defaults(func=cmd_coverage)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
