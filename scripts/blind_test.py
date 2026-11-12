#!/usr/bin/env python3
"""盲测：把「像不像我」变成一个能算的数。

评测集只能证明「闸门没松」，证明不了「改写像你」。要知道后者，唯一的办法是
把真话和改写混在一起，让人自己认——认出率接近抛硬币，才说明改写真的混得进去。

子命令：
    template  打印一条空白用例骨架
    make      读 cases.jsonl，打乱成一张无标签的 A/B 表
    score     读回答案，算认出率、显著性与作废条件

用法：
    python scripts/blind_test.py make --in cases.jsonl --out rounds/r1 --seed 7
    # 打开 rounds/r1/sheet.md 逐条判，把答案写成一行
    python scripts/blind_test.py score --round rounds/r1 --picks "B,A,B,A,-,B"

退出码：0 通过（分不出来），1 失败（能分辨，风格层没兜住），2 无法判定。

设计约束：只用标准库，不联网，不调用模型。答案放在 key.json，
判的时候只看 sheet.md —— 这一条是整套东西唯一有效的理由。
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path

# 两条候选相似到这个程度，答对答错都说明不了问题：改写几乎没动
TOO_CLOSE = 0.85
# 少于这个条数不下结论：八条里全对也只有 p≈0.004，再多就全靠运气
MIN_N = 8
# 认得出到这个比例并且显著，就算红灯
RED_RATE = 0.70
# 位置偏好：同一边被选了这么多，多半是在按位置点，不是在读文本
POSITION_BIAS = 0.85


# ---------- 统计 ----------

def _pmf(k: int, n: int) -> float:
    return math.comb(n, k) * 0.5 ** n


def p_two_sided(hits: int, n: int) -> float:
    """精确二项双侧 p：观察到 hits 或更极端结果的概率。

    不做正态近似。n 通常只有十来条，近似会把「8 条全对」算成 p=0.008 之外
    的数，而精确值是 1/256。样本小的时候，近似不是省事，是给出错的结论。
    """
    if n <= 0:
        return 1.0
    obs = _pmf(hits, n)
    return min(1.0, sum(_pmf(i, n) for i in range(n + 1)
                        if _pmf(i, n) <= obs * (1 + 1e-12)))


def p_at_least(hits: int, n: int) -> float:
    """单侧 p：至少有这么多条被认出来。红不红看这个。"""
    return min(1.0, sum(_pmf(i, n) for i in range(hits, n + 1)))


# ---------- 读数与写盘 ----------

def load_cases(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"找不到用例文件：{path}")
    rows, seen = [], set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.exit(f"{path}:{lineno} 不是合法 JSON：{exc}")
        cid = str(row.get("id") or f"c{lineno}").strip()
        if cid in seen:
            sys.exit(f"{path}:{lineno} id 重复：{cid}")
        seen.add(cid)
        for field in ("mine", "generated"):
            if not str(row.get(field) or "").strip():
                sys.exit(f"{path}:{lineno}（{cid}）缺 {field}：这两句缺一条就没得比")
        rows.append({
            "id": cid,
            "context": str(row.get("context") or "").strip(),
            "mine": str(row["mine"]).strip(),
            "generated": str(row["generated"]).strip(),
        })
    if not rows:
        sys.exit(f"{path} 里没有可用用例")
    return rows


def similarity(mine: str, generated: str) -> float:
    return difflib.SequenceMatcher(None, mine, generated).ratio()


def build_sheet(items: list[dict], excluded: list[dict], seed: int) -> str:
    lines = [
        "# 盲测表",
        "",
        f"共 {len(items)} 条。每条下面两句话：**一句是他本人打的，一句是改写。**",
        "哪句是他打的？凭第一反应，不要回头找线索。",
        "",
        "判完把答案写成一行（`-` 表示这条跳过不判），例如：`B,A,B,-,A`",
        "",
    ]
    if excluded:
        lines.append(f"另有 {len(excluded)} 条已剔除：两句几乎一样，答对答错都说明不了问题。")
        lines.append("")
    for idx, item in enumerate(items, 1):
        lines.append(f"## {idx:02d}")
        if item["context"]:
            lines.append(f"上文：{item['context']}")
        lines.append("")
        lines.append(f"A. {item['a_text']}")
        lines.append("")
        lines.append(f"B. {item['b_text']}")
        lines.append("")
        lines.append("答案：__")
        lines.append("")
    lines.append("---")
    lines.append(f"判完跑：`python scripts/blind_test.py score --round <本目录> --picks \"你的答案\"`")
    lines.append("（seed=%d。答案在 key.json，交卷前不要打开。）" % seed)
    return "\n".join(lines) + "\n"


def cmd_make(args) -> int:
    cases = load_cases(Path(args.src))
    out = Path(args.out)
    rng_seed = args.seed

    items, excluded = [], []
    for case in cases:
        sim = similarity(case["mine"], case["generated"])
        if sim >= TOO_CLOSE and not args.keep_close:
            excluded.append({"id": case["id"], "similarity": round(sim, 3)})
            continue
        # 每条的左右位置由 seed+id 决定：同一份用例重跑得到同一张表，
        # 但换 seed 就重新洗，免得「上次第 3 条是 A」变成记忆线索。
        flip = random.Random(f"{rng_seed}:{case['id']}").random() < 0.5
        a_text, b_text = (case["generated"], case["mine"]) if flip else (case["mine"], case["generated"])
        items.append({
            "id": case["id"],
            "context": case["context"],
            "a_text": a_text,
            "b_text": b_text,
            "a_is": "gen" if flip else "mine",
            "len_ratio": round(len(case["generated"]) / max(1, len(case["mine"])), 3),
            "len_mine": len(case["mine"]),
            "len_gen": len(case["generated"]),
        })

    if not items:
        sys.exit("剔除之后一条都不剩：这批改写和原话太像，换一批更像真实改写的样本")

    out.mkdir(parents=True, exist_ok=True)
    (out / "sheet.md").write_text(build_sheet(items, excluded, rng_seed), encoding="utf-8")
    key = {
        "seed": rng_seed,
        "n": len(items),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "excluded": excluded,
        "items": [{"id": it["id"], "a_is": it["a_is"],
                   "len_mine": it["len_mine"], "len_gen": it["len_gen"]} for it in items],
    }
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")

    print(f"已生成 {out / 'sheet.md'}")
    print(f"  条数：{len(items)}" + (f"，剔除 {len(excluded)} 条（几乎没改写）" if excluded else ""))
    if excluded:
        print("  剔除：" + "、".join(e["id"] for e in excluded))
    if len(items) < MIN_N:
        print(f"  [提醒] 只有 {len(items)} 条，少于 {MIN_N} 条算不出结论，建议再加几条")
    print("  判完把答案写成一行，跑 score。答案在 key.json，交卷前别打开。")
    return 0


def parse_picks(raw: str, n: int) -> list[str]:
    picks = [p.strip().upper() for p in raw.replace("，", ",").replace(" ", ",").split(",") if p.strip()]
    if len(picks) != n:
        sys.exit(f"答案条数对不上：表里有 {n} 条，你给了 {len(picks)} 个（用逗号分隔，跳过写 -）")
    bad = [p for p in picks if p not in ("A", "B", "-", "?")]
    if bad:
        sys.exit(f"答案只能是 A / B / -，这几条不认识：{', '.join(bad)}")
    return picks


def cmd_score(args) -> int:
    round_dir = Path(args.round)
    key_path = round_dir / "key.json"
    if not key_path.exists():
        sys.exit(f"找不到 {key_path}：这是答案，没有它算不出认出率")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    items = key["items"]
    picks = parse_picks(args.picks, len(items))

    hits = valid = 0
    pos = {"A": 0, "B": 0}
    len_picked_gen = []
    for item, pick in zip(items, picks):
        if pick not in ("A", "B"):
            continue
        valid += 1
        pos[pick] += 1
        # a_is 只有 mine / gen 两种取值：选中 A 且 A 是本人的，或选中 B 且 B 是本人的
        picked_is_mine = (pick == "A") == (item["a_is"] == "mine")
        if picked_is_mine:
            hits += 1
        else:
            len_picked_gen.append(item["len_gen"])

    if valid == 0:
        sys.exit("一条都没判，算不出东西")

    rate = hits / valid
    p2 = p_two_sided(hits, valid)
    p1 = p_at_least(hits, valid)
    bias = max(pos.values()) / valid
    # 长度线索：改写比原话长的条目占几成。如果几乎全朝一边，
    # 他可能是靠长短认出来的，不是靠语气——这次结果就有一部分不算数。
    diffs = [it["len_gen"] - it["len_mine"] for it in items]
    longer = sum(1 for d in diffs if d > 0) / len(diffs)
    len_bias = max(longer, 1 - longer)
    avg_mine = sum(it["len_mine"] for it in items) // len(items)
    avg_gen = sum(it["len_gen"] for it in items) // len(items)

    verdict, code = "", 0
    if valid < MIN_N:
        verdict, code = f"样本不足：只有 {valid} 条，{MIN_N} 条以下不下结论", 2
    elif bias >= POSITION_BIAS:
        verdict, code = f"作废：{int(bias * 100)}% 的答案落在同一侧，像是在按位置点，不是在读文本", 2
    elif rate >= RED_RATE and p1 < 0.05:
        verdict, code = "能分辨：改写里还有明显不是他说话的痕迹，风格层没兜住", 1
    elif rate <= 0.20:
        verdict, code = "反常：几乎全认错，先确认这次没偷看 key.json、也没照长度猜", 2
    elif 0.4 <= rate <= 0.6:
        verdict, code = "分不出来：认出率和抛硬币一样，这批改写混得进去", 0
    else:
        verdict, code = "方向偏了但没到显著，再攒几条样本", 2

    if code == 0 and len_bias >= 0.9 and valid >= MIN_N:
        # 长短始终朝一边、而且差得明显，那这次可能是长度在替他答，不是语气。
        # 只差一两个字不算线索，否则这条提醒会天天响，响到最后没人看。
        gap = max(avg_gen, avg_mine) / max(1, min(avg_gen, avg_mine))
        if gap >= 1.4:
            verdict += f"（但改写普遍比原话长/短 {gap:.1f} 倍，这次有一部分可能是长度在替他答）"

    print(f"盲测结果 · {round_dir.name}")
    print(f"  条数：{valid}" + (f"（另有 {len(items) - valid} 条跳过）" if valid != len(items) else ""))
    if key.get("excluded"):
        print(f"  已剔除：{len(key['excluded'])} 条几乎没改写")
    print(f"  认出率：{hits}/{valid} = {rate * 100:.0f}%   （随机基线 50%）")
    print(f"  双侧精确 p = {p2:.3f}，单侧 p = {p1:.3f}（n={valid}，不做正态近似）")
    print(f"  位置：选 A {pos['A']} 次，选 B {pos['B']} 次")
    print(f"  长度线索：{len_bias * 100:.0f}% 的条目长短朝同一侧")
    print(f"  字数：你的原话平均 {avg_mine} 字，改写平均 {avg_gen} 字")
    if len_picked_gen:
        print(f"  被你当成自己打的改写：{len(len_picked_gen)} 条，平均 "
              f"{sum(len_picked_gen) // len(len_picked_gen)} 字")
    print(f"  结论：{verdict}")

    if args.json:
        print(json.dumps({"round": round_dir.name, "n": valid, "hits": hits, "rate": round(rate, 4),
                          "p_two": round(p2, 4), "p_one": round(p1, 4),
                          "position": pos, "len_bias": round(len_bias, 3),
                          "verdict": verdict, "code": code}, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(
            f"# 盲测结果 {round_dir.name}\n\n- 认出率：{hits}/{valid} = {rate * 100:.0f}%\n"
            f"- 双侧 p：{p2:.3f}\n- 结论：{verdict}\n", encoding="utf-8")
    return code


def cmd_template(_args) -> int:
    print(json.dumps({
        "id": "b1",
        "context": "她：今天好累啊",
        "mine": "那早点睡 明天再说",
        "generated": "听起来今天挺熬人的，先休息吧",
    }, ensure_ascii=False))
    print("  ↑ 一行一条。mine 是你当时真打出去的话，generated 是改写。", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="盲测：认出率越低，说明改写越像你")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_make = sub.add_parser("make", help="生成无标签的 A/B 表")
    p_make.add_argument("--in", dest="src", required=True, help="cases.jsonl")
    p_make.add_argument("--out", required=True, help="输出目录，如 rounds/r1")
    p_make.add_argument("--seed", type=int, default=7, help="换一个 seed 就重新洗一次左右位置")
    p_make.add_argument("--keep-close", action="store_true", help="保留几乎没改写的条目")
    p_make.set_defaults(func=cmd_make)

    p_score = sub.add_parser("score", help="算认出率")
    p_score.add_argument("--round", required=True, help="make 的输出目录")
    p_score.add_argument("--picks", required=True, help='如 "B,A,B,-,A"')
    p_score.add_argument("--json", action="store_true", help="追加一行机器可读结果")
    p_score.add_argument("--out", help="把结论写成 markdown")
    p_score.set_defaults(func=cmd_score)

    p_tpl = sub.add_parser("template", help="打印一条空白用例骨架")
    p_tpl.set_defaults(func=cmd_template)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
