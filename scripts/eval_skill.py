#!/usr/bin/env python3
"""评测集：固定场景 + 固定候选，机械核对两道闸门的表现。

    python scripts/eval_skill.py
    python scripts/eval_skill.py -v      # 逐条打印

不调模型、不联网、不需要风格卡。它测的是**下限**：

- 阶段禁止的策略有没有被拦下（`repairing` 不给邀约）
- 超长、语气词、AI 味有没有被砍掉
- 术语有没有漏进候选
- 硬目标、自我底线有没有生效

测不了「这条回得妙不妙」——那只能靠人看。这也是它比「让模型给自己打分」
可靠的地方：同样的输入永远同样的结论，改坏了会立刻变红。

用例在 `evals/cases.jsonl`，一条一行；加场景只要往后追加，不用改代码。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evals" / "cases.jsonl"

sys.path.insert(0, str(ROOT / "scripts"))
import profile_tool  # noqa: E402
import style_tool  # noqa: E402

# 候选是给用户看的，这些词一个都不许出现。
# 运行时闸门没管这一层（AI_SMELL 只覆盖书面语），评测这边补上。
TERMS = [
    "依恋", "边界感", "共情", "情绪价值", "原生家庭", "课题分离",
    "沟通成本", "回避型", "焦虑型", "防御机制", "非暴力沟通",
    "需求层次", "关系动力", "投射效应",
]

STRATEGIES = ("minimal", "care", "substantive", "advance", "repair", "hold")
STAGES = tuple(profile_tool.STAGE)


def load_cases() -> list[dict]:
    if not CASES.exists():
        raise SystemExit(f"找不到评测用例：{CASES}")
    cases: list[dict] = []
    for lineno, raw in enumerate(CASES.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith("//"):
            continue
        try:
            cases.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"cases.jsonl 第 {lineno} 行不是合法 JSON：{exc}")
    return cases


def case_context(case: dict) -> tuple[dict, dict]:
    """把用例里的档案片段变成 guard 要的两个 dict。"""
    slot = {
        "person": {"alias": "她", "stage": case["stage"]},
        "facts": case.get("facts", []),
        "reads": [], "unknowns": [], "landmines": [], "soothers": [],
        "promises": [], "timeline": [], "goals": case.get("goals", []),
    }
    me = {"items": case.get("self", [])}
    return slot, me


def judge(text: str, strategy: str, case: dict, slot: dict, me: dict) -> dict:
    """跑三道机械检查，返回每一道的结果。"""
    stage = case["stage"]
    g = profile_tool.guard(text, me, slot, strategy, stage, case.get("danger"))
    s = style_tool.check(text, None, strategy)
    hits = [t for t in TERMS if t in text]
    denied = strategy in profile_tool.stage_card(stage)["deny"] if strategy else False
    return {
        "content": g["ok"] and not denied,
        "style": s["ok"],
        "term": not hits,
        "problems": list(g["problems"]) + list(s["problems"])
        + ([f"阶段 {stage} 禁止 {strategy}"] if denied else [])
        + ([f"出现术语：{'、'.join(hits)}"] if hits else []),
    }


def run(verbose: bool = False) -> int:
    cases = load_cases()
    good_total = good_pass = 0
    bad_total = bad_caught = 0
    failures: list[str] = []
    seen_stages: set[str] = set()
    seen_strategies: set[str] = set()
    seen_high_danger = False

    print(f"评测集 {len(cases)} 条用例")
    for case in cases:
        cid = case.get("id", "?")
        stage = case.get("stage", "")
        if stage not in profile_tool.STAGE:
            failures.append(f"{cid}: 阶段「{stage}」不在六档里")
            continue
        seen_stages.add(stage)
        danger = case.get("danger")
        if danger is not None:
            if not isinstance(danger, int) or not 0 <= danger <= 9:
                failures.append(f"{cid}: danger 必须是 0-9 的整数，拿到的是 {danger!r}")
            elif danger >= 7:
                seen_high_danger = True
        slot, me = case_context(case)

        goods = case.get("good", [])
        if len(goods) < 3:
            failures.append(f"{cid}: 只有 {len(goods)} 条好候选，应该 3 条")
        strategies = [g["strategy"] for g in goods]
        if len(set(strategies)) < 3:
            failures.append(f"{cid}: 三条候选的策略不互斥（{strategies}），换措辞不算换策略")
        seen_strategies.update(strategies)

        for cand in goods:
            good_total += 1
            verdict = judge(cand["text"], cand["strategy"], case, slot, me)
            ok = all(verdict[k] for k in ("content", "style", "term"))
            if ok:
                good_pass += 1
                if verbose:
                    print(f"  ok   {cid} [{cand['strategy']}] {cand['text']}")
            else:
                failures.append(
                    f"{cid} 好候选被拦 [{cand['strategy']}] {cand['text']}\n      "
                    + "；".join(verdict["problems"] or ["原因未记录"]))

        for cand in case.get("bad", []):
            bad_total += 1
            verdict = judge(cand["text"], cand.get("strategy", ""), case, slot, me)
            gate = cand.get("gate", "either")
            caught = (not verdict[gate]) if gate in ("content", "style", "term") else not all(
                verdict[k] for k in ("content", "style", "term"))
            if caught:
                bad_caught += 1
                if verbose:
                    print(f"  cut  {cid} [{gate}] {cand['text']}  ← {cand.get('why', '')}")
            else:
                failures.append(
                    f"{cid} 坏候选漏放 [{gate}] {cand['text']}  ← {cand.get('why', '')}")

    print(f"  好候选 {good_total} 条 · 通过 {good_pass} · 被误拦 {good_total - good_pass}")
    print(f"  坏候选 {bad_total} 条 · 拦住 {bad_caught} · 漏放 {bad_total - bad_caught}")
    print(f"  覆盖：阶段 {len(seen_stages)}/{len(STAGES)} · 策略 {len(seen_strategies)}/{len(STRATEGIES)}")

    missing_stage = [s for s in STAGES if s not in seen_stages]
    missing_strategy = [s for s in STRATEGIES if s not in seen_strategies]
    if missing_stage:
        failures.append(f"评测集没有覆盖这些阶段：{'、'.join(missing_stage)}")
    if missing_strategy:
        failures.append(f"评测集没有覆盖这些策略：{'、'.join(missing_strategy)}")
    # 安全阈值是唯一涉及人身安全的规则。它曾经一条用例都没有，改坏了也没人知道。
    if not seen_high_danger:
        failures.append("没有一条 danger≥7 的用例：高危路径无人看守")

    for f in failures:
        print(f"  [失败] {f}")

    if failures:
        print(f"结果：失败（{len(failures)} 处）")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(verbose="-v" in sys.argv or "--verbose" in sys.argv))
