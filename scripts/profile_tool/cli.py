"""CLI 入口：参数解析与子命令分发。

main() 是唯一入口，validate_skill / eval_skill 通过 profile_tool.main 调用它。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .constants import (
    CONFIDENCE,
    GOAL_KINDS,
    HORIZONS,
    KINDS,
    SELF_KINDS,
    STAGE,
)
from .commands import (
    cmd_accept, cmd_add, cmd_balance, cmd_brief, cmd_check_promise,
    cmd_export, cmd_forget, cmd_goal_add, cmd_goal_close, cmd_goal_list,
    cmd_guard, cmd_init, cmd_kb, cmd_list, cmd_prefs, cmd_reflect,
    cmd_search, cmd_self_add, cmd_self_export, cmd_self_forget,
    cmd_self_init, cmd_self_list, cmd_stage, cmd_stale, cmd_stats,
    cmd_trace, cmd_verify,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="恋爱档案")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def slot_arg(p):
        p.add_argument("--slot", default="couple_early")

    p = sub.add_parser("init", help="建立档案")
    slot_arg(p)
    p.add_argument("--alias", default="她")
    # 其余命令都做了 choices，只有 init 没有：拼错的阶段能一路写进档案，
    # brief 之后才提示「未知阶段」，脏值已经在那儿了。
    p.add_argument("--stage", default="warming", choices=list(STAGE))
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
    p.add_argument("--tag", nargs="*", default=[],
                   help="同义词/类别词，检索时和正文一起匹配。如：芒果 水果 吃")
    p.add_argument("--core", action="store_true",
                   help="常驻：每次都带上，不靠检索。只给「说了就必须遵守」的事实")
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
    p.add_argument("--danger", type=int, default=None, choices=range(0, 10))
    p.set_defaults(func=cmd_guard)

    p = sub.add_parser("verify", help="三条候选一次过两道闸门")
    slot_arg(p)
    p.add_argument("--candidate", action="append", default=[],
                   help="策略:文字，可重复。策略可省")
    p.add_argument("--file", default="", help='JSON 文件：[{"strategy":"minimal","text":"..."}]')
    p.add_argument("--stage", default="", choices=[""] + list(STAGE))
    p.add_argument("--danger", type=int, default=None, choices=range(0, 10),
                   help="判出来的危险度 0-9。≥7 时邀约和给方案一律拦下")
    p.add_argument("--then", default="", metavar="她回的那句",
                   help="续写模式：她回了这句话，这一轮只给一句。判进退、查重复与连推")
    p.add_argument("--prev", default="", metavar="策略:上一轮发出的那句",
                   help="续写模式必给：上一轮实际发出去的是哪条")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("kb", help="意图 × 阶段 → 该读的 2–3 篇知识")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import kb_route as _kb
    _data = _kb.load()
    p.add_argument("--intent", required=True, choices=list(_data["intents"]),
                   help="判出来的意图，六选一")
    p.add_argument("--stage", default="", choices=[""] + list(STAGE))
    p.add_argument("--danger", type=int, default=None, choices=range(0, 10))
    p.add_argument("--flag", action="append", default=[],
                   help="特殊情形，可重复：" + " / ".join(_data.get("flags", {})))
    p.set_defaults(func=cmd_kb)

    p = sub.add_parser("prefs", help="他对策略的偏好统计（只影响排序）")
    slot_arg(p)
    p.set_defaults(func=cmd_prefs)

    p = sub.add_parser("trace", help="把判→取→写→过闸串成决策记录，校验自不自洽")
    p.add_argument("--file", default="", help="决策记录 JSON 文件")
    p.add_argument("--json", default="", help="决策记录 JSON 字符串（和 --file 二选一）")
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser("balance", help="投入对账：摆两边客观行为，看是不是单向")
    p.add_argument("--json", default="", help="行为记录 JSON（mine/hers 各四类）")
    p.set_defaults(func=cmd_balance)

    p = sub.add_parser("reflect", help="复盘回流：把这次踩的坑、漏的事实、你的改法记下来，下次别犯")
    p.add_argument("--json", default="", help="复盘记录 JSON")
    p.add_argument("--file", default="", help="复盘记录 JSON 文件（和 --json 二选一）")
    p.add_argument("--slot", default="", help="哪个档案（缺省自动收敛到唯一那份）")
    p.set_defaults(func=cmd_reflect)

    args = ap.parse_args(argv)
    return args.func(args)
