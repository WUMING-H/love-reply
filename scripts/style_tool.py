#!/usr/bin/env python3
"""风格工具：统计、校验、回流。

子命令：
    profile   从真实语料算 metrics，生成/更新风格卡
    check     校验一条候选是否符合风格
    feedback  记录用户点选或改写
    show      查看当前风格卡

存储位置：%LOVE_REPLY_HOME%，未设置时用本 Skill 目录下的 data/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")
LATIN = re.compile(r"[a-zA-Z]")
PARTICLES = set("啊吧呢嘛咯呗哦呀哈唉诶欸喔噢嘞捏")
HIGH_RISK = set("呢啦呀嘛呗咯")

AI_SMELL = [
    "此外", "总之", "综上", "总而言之", "建议你", "我理解你的感受", "我理解你",
    "希望这能帮到你", "首先", "其次", "不妨", "或许可以", "某种程度",
    "需要注意的是", "值得注意的是", "让我们", "接下来", "如果你需要",
    "随时告诉我", "希望能帮到", "深呼吸", "我明白你的意思",
]

# 无风格卡时的安全默认：短、口语、不夸张
SAFE_DEFAULT = {
    "chars_p50": 12,
    "chars_p90": 34,
    "short_ratio": 0.5,
    "emoji_per_100": 0.0,
    "terminal_period": 0.1,
    "high_risk_particle_per_100": 0.0,
}

# 无风格卡时的绝对档位：默认值本身就是「合理区间」，不是这个人的统计，
# 所以不能套系数，直接给固定上限。
NO_CARD_LIMITS = {
    "minimal": 16, "care": 16, "hold": 16,
    "substantive": 40, "repair": 34, "advance": 26, "auto": 26,
}


def home() -> Path:
    env = os.environ.get("LOVE_REPLY_HOME")
    if env:
        p = Path(env).expanduser()
    else:
        # 数据和 skill 放一起，但独立在 data/ 下：更新 skill 文件时不会碰到个人数据
        p = Path(__file__).resolve().parent.parent / "data"
    return p


def card_path(slot: str) -> Path:
    return home() / "style" / f"{slot}.json"


def load_card(slot: str) -> dict | None:
    p = card_path(slot)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_card(slot: str, card: dict) -> Path:
    p = card_path(slot)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def pct(nums: list[int], q: float) -> int:
    if not nums:
        return 0
    s = sorted(nums)
    if len(s) == 1:
        return s[0]
    return s[min(len(s) - 1, int(round((len(s) - 1) * q)))]


def compute(messages: list[str]) -> dict:
    n = len(messages)
    if n == 0:
        raise ValueError("没有消息可统计")
    lens = [len(m) for m in messages]
    total = sum(lens) or 1
    joined = "".join(messages)
    return {
        "source_count": n,
        "chars_p50": int(median(lens)),
        "chars_p90": pct(lens, 0.9),
        "chars_max": max(lens),
        "short_ratio": round(sum(1 for l in lens if l <= 6) / n, 2),
        "emoji_per_100": round(len(EMOJI.findall(joined)) / total * 100, 1),
        "terminal_period": round(sum(1 for m in messages if m.rstrip().endswith("。")) / n, 2),
        "exclaim_rate": round(sum(1 for m in messages if "！" in m or "!" in m) / n, 2),
        "question_mark_rate": round(sum(1 for m in messages if "？" in m or "?" in m) / n, 2),
        "particle_per_100": round(sum(1 for c in joined if c in PARTICLES) / total * 100, 1),
        "high_risk_particle_per_100": round(
            sum(1 for c in joined if c in HIGH_RISK) / total * 100, 1),
        "latin_ratio": round(len(LATIN.findall(joined)) / total, 3),
    }


def ngrams(messages: list[str], min_freq: int = 3, topk: int = 20) -> list[str]:
    stop = set("我们你们他们这个那个就是然后所以但是因为可以什么怎么一个一下现在时候知道".split())
    cnt: Counter[str] = Counter()
    for m in messages:
        for n in range(2, 5):
            for i in range(len(m) - n + 1):
                g = m[i:i + n]
                if any(s in g for s in stop) or g.isdigit() or not g.strip():
                    continue
                cnt[g] += 1
    return [g for g, c in cnt.most_common(topk) if c >= min_freq]


def infer_avoid(messages: list[str]) -> list[str]:
    """从「从不出现」反推硬禁用项。正面描述模型执行不了，禁用项能 100% 执行。"""
    n = len(messages)
    joined = "".join(messages)
    avoid = []
    if not EMOJI.search(joined):
        avoid.append("不用 emoji")
    if not re.search(r"(.)\1\1", joined):
        avoid.append("不用叠字")
    if not any(c in joined for c in HIGH_RISK):
        avoid.append("不用「呢、啦、呀」")
    if "～" not in joined and "~" not in joined:
        avoid.append("不用波浪号")
    if sum(1 for m in messages if m.rstrip().endswith("。")) / n < 0.1:
        avoid.append("不加句号")
    if not re.search(r"[笑哈]{2,}", joined):
        avoid.append("不用「哈哈」")
    return avoid


def check(text: str, card: dict | None, strategy_name: str = "auto") -> dict:
    m = (card or {}).get("metrics") or SAFE_DEFAULT
    strategy = (card or {}).get("strategy") or {}
    banned = list(strategy.get("avoid") or []) + AI_SMELL
    problems: list[str] = []

    length = len(text)
    p50 = m.get("chars_p50") or 12
    p90 = m.get("chars_p90") or 34

    # 上限必须按策略分档：minimal 该短，substantive 天生更长。
    # 用同一把尺子会把「给具体时间方案」这类必要长句全拦掉。
    # 无卡时用绝对档位（默认值不是这个人的统计，套系数会算出 74 字这种没意义的上限）。
    if card is None:
        hi = NO_CARD_LIMITS.get(strategy_name, 26)
        # 没有风格卡就没有下限依据。拍一个 3 字会误杀「没有」「不去」「好啊」
        # 这种正常的两字回复——它们是中文聊天里最高频的答法，逼模型改长反而失真。
        lo = 1
    else:
        if strategy_name in ("minimal", "care", "hold"):
            hi = max(int(p90 * 1.2), 18)
        elif strategy_name in ("substantive", "repair"):
            hi = max(int(p90 * 2.2), int(p50 * 3), 34)
        else:  # advance / auto
            hi = max(int(p90 * 1.6), int(p50 * 2.2), 24)
        lo = min(6, max(2, int(p50 * 0.4)))

    if length > hi:
        problems.append(f"太长：{length} 字，{strategy_name} 档目标 ≤{hi}。先砍，别解释")
    elif length < lo and length > 0:
        problems.append(f"太短：{length} 字，目标 ≥{lo}，可能丢了信息")

    if text.rstrip().endswith("。") and (m.get("terminal_period", 0) or 0) < 0.15:
        problems.append("结尾有句号，这个人基本不加句号")

    emoji_n = len(EMOJI.findall(text))
    allowed = max(0, int(length * (m.get("emoji_per_100") or 0) / 100 * 2))
    if emoji_n > allowed:
        problems.append(f"emoji {emoji_n} 个，最多 {allowed} 个")

    for w in banned:
        if w in text:
            problems.append(f"命中禁用：{w}")

    if (m.get("high_risk_particle_per_100", 0) or 0) < 0.5:
        hit = [c for c in HIGH_RISK if c in text]
        if hit:
            problems.append(f"用了语气词「{''.join(hit)}」，这个人几乎不用")

    if re.search(r"[！!]", text) and (m.get("exclaim_rate", 0) or 0) < 0.1:
        problems.append("用了感叹号，这个人基本不用")

    # 结构问题：书面语连词、总结句
    if re.search(r"(因为|所以|虽然|但是|不过)", text) and length > 25:
        problems.append("有书面语连词，长句里出现像作文")

    return {
        "ok": not problems,
        "length": length,
        "target_range": [lo, hi],
        "strategy": strategy_name,
        "problems": problems,
        "has_card": card is not None,
    }


def cmd_profile(args) -> int:
    if args.text:
        messages = [args.text]
    else:
        p = Path(args.file)
        if not p.exists():
            print(json.dumps({"ok": False, "error": f"文件不存在：{p}"}, ensure_ascii=False))
            return 1
        messages = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.strip().startswith("#")]
    if not messages:
        print(json.dumps({"ok": False, "error": "没有有效消息"}, ensure_ascii=False))
        return 1

    old = load_card(args.slot) or {}
    card = {
        "slot": args.slot,
        "version": old.get("version", 0) + 1,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "metrics": compute(messages),
        "strategy": old.get("strategy") or {
            "length": "短，能五个字说完不写八个字",
            "punctuation": "几乎不用句号",
            "anger": "待校准",
            "comfort": "待校准",
            "apology": "待校准",
            "humor": "待校准",
            "avoid": infer_avoid(messages),
        },
        "samples": old.get("samples") or {},
    }
    if not old.get("strategy"):
        card["strategy"]["avoid"] = infer_avoid(messages)
    card["ngram"] = ngrams(messages)

    path = save_card(args.slot, card)
    print(json.dumps({
        "ok": True, "written": str(path),
        "sample_count": len(messages),
        "metrics": card["metrics"],
        "inferred_avoid": card["strategy"]["avoid"],
        "note": "strategy 里的 anger/comfort/apology 需要人工或对话校准，脚本不猜",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_check(args) -> int:
    card = load_card(args.slot)
    result = check(args.text, card, args.strategy)
    result["slot"] = args.slot
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


def cmd_feedback(args) -> int:
    p = home() / "feedback.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "slot": args.slot,
        "kind": args.kind,
        "ai_text": args.ai,
        "user_text": args.user,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # 用户改过的句子直接进 samples，这是最强的信号
    added = False
    if args.kind == "edited" and args.user:
        card = load_card(args.slot) or {"slot": args.slot, "metrics": SAFE_DEFAULT,
                                        "strategy": {}, "samples": {}}
        scene = args.scene or "casual"
        card.setdefault("samples", {}).setdefault(scene, [])
        if args.user not in card["samples"][scene]:
            card["samples"][scene].append(args.user)
            card["samples"][scene] = card["samples"][scene][-20:]
            save_card(args.slot, card)
            added = True
    print(json.dumps({"ok": True, "logged": str(p), "sample_added": added},
                     ensure_ascii=False))
    return 0


def cmd_show(args) -> int:
    card = load_card(args.slot)
    if not card:
        print(json.dumps({
            "exists": False, "slot": args.slot,
            "path": str(card_path(args.slot)),
            "fallback": SAFE_DEFAULT,
            "hint": "没有风格卡，先用安全默认。跑 profile 从真实语料生成。",
        }, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(card, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="风格工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profile", help="从语料生成风格卡")
    p.add_argument("--file", help="每行一条真实消息")
    p.add_argument("--text", help="单条")
    p.add_argument("--slot", default="couple_early")
    p.set_defaults(func=cmd_profile)

    c = sub.add_parser("check", help="校验一条候选")
    c.add_argument("--text", required=True)
    c.add_argument("--slot", default="couple_early")
    c.add_argument("--strategy", default="auto",
                   choices=["auto", "minimal", "care", "hold",
                            "substantive", "repair", "advance"],
                   help="候选属于哪种策略，长度上限按此分档")
    c.set_defaults(func=cmd_check)

    f = sub.add_parser("feedback", help="记录点选或改写")
    f.add_argument("--slot", default="couple_early")
    f.add_argument("--kind", required=True, choices=["chosen", "rejected", "edited"])
    f.add_argument("--ai", required=True)
    f.add_argument("--user", default="")
    f.add_argument("--scene", default="")
    f.set_defaults(func=cmd_feedback)

    s = sub.add_parser("show", help="查看风格卡")
    s.add_argument("--slot", default="couple_early")
    s.set_defaults(func=cmd_show)

    args = ap.parse_args()
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
