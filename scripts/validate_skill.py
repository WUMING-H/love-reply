#!/usr/bin/env python3
"""完整性自检：文件是否齐、路由是否可达、主文件是否超预算。

    python scripts/validate_skill.py

退出码 0 通过，1 有硬错误，2 只有警告。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = [
    "SKILL.md",
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "NOTICE.md",
    "references/judge.md",
    "references/compose.md",
    "references/style-guide.md",
    "references/profile.md",
    "references/self.md",
    "references/stages.md",
    "references/routes.md",
    "prompts/standalone.md",
    "prompts/profile-interview.md",
    "prompts/self-interview.md",
    "scripts/style_tool.py",
    "scripts/profile_tool.py",
    "scripts/eval_skill.py",
    "evals/cases.jsonl",
    "licenses/goutoujunshi-LICENSE",
]

# 主文件太长会挤占对话上下文，这是硬预算
SKILL_BUDGET_BYTES = 12_000
KB_MIN_DOCS = 40

# 正文关键块。脚本冒烟测得出手写代码的死活，测不出正文少了一整节——
# 2026-11-12 那次重构把「改风格」「语义冻结」「事实/推测/未知」三块整体删掉，
# validate 依然全绿零警告。以下每条都是承重的，缺一个就等于对应步骤静默失效。
CONTENT_SPECS: dict[str, list[tuple[str, str]]] = {
    "SKILL.md": [
        ("三段流程命名（判 → 写 → 过闸）", r"判\s*→\s*写\s*→\s*过闸"),
        ("四条原则", r"四条原则"),
        ("两条红线", r"两条红线"),
        ("六阶段名单", r"stranger[\s\S]{0,200}warming[\s\S]{0,200}dating[\s\S]{0,200}"
                       r"couple_early[\s\S]{0,200}couple_stable[\s\S]{0,200}repairing"),
        ("事实 / 推测 / 未知三栏", r"事实\s*/\s*推测\s*/\s*未知"),
        ("七问字段", r"give_substance"),
        ("危险度阈值", r"danger\s*[>≥]=?\s*7"),
        ("六种策略", r"minimal[\s\S]*hold"),
        ("临场取样", r"style_tool\.py sample"),
        ("改风格", r"改风格"),
        ("语义冻结", r"语义冻结"),
        ("冷启动不阻塞", r"冷启动"),
        ("输出格式章节", r"^## 输出格式"),
        ("输出反面例子", r"反面例子"),
        ("硬约束章节", r"^## 硬约束"),
        ("危机转介入口", r"危机转介\.md"),
        ("多份档案先问", r"多份时，先问"),
        ("无 bash 走 standalone", r"prompts/standalone\.md"),
    ],
    "AGENTS.md": [
        ("三段流程命名", r"判\s*→\s*写\s*→\s*过闸"),
        ("派生物声明", r"派生物"),
        ("四条原则", r"四条原则"),
        ("两条红线", r"两条红线"),
        ("六阶段名单", r"stranger[\s\S]{0,200}repairing"),
        ("危险度阈值", r"danger\s*[>≥]=?\s*7"),
        ("临场取样", r"sample --file"),
        ("语义冻结", r"语义冻结"),
        ("冷启动不阻塞", r"冷启动"),
        ("输出反面例子", r"反面例子"),
        ("硬约束章节", r"^## 硬约束"),
        ("多份档案先问", r"多份时，先问"),
    ],
    "prompts/standalone.md": [
        ("四条原则（与主文件同一套）", r"四条原则"),
        ("两条红线", r"两条红线"),
        ("六阶段名单", r"stranger[\s\S]{0,200}repairing"),
        ("危险度阈值", r"危险度\s*[≥>=]"),
        ("临场取样", r"取样"),
        ("语义冻结", r"语义冻结"),
        ("冷启动安全默认", r"冷启动"),
        ("输出格式", r"【输出格式"),
        ("输出反面例子", r"反面例子"),
        ("不许替用户承诺", r"不许替我承诺"),
    ],
}

# 三份入口的条目数必须一致。两份互相矛盾的指令，模型不会报错，
# 只会随便挑一条执行，而且不会告诉用户它挑了哪条。
PRINCIPLE_COUNT = 4
HARD_RULE_COUNT = 7

# 反引号里写的相对路径必须真实存在，断链比没写更糟
LOCAL_REF = re.compile(r"`((?:references|prompts|documentation|scripts)/[^`\s]+?\.(?:md|py))`")
NUMBERED = re.compile(r"^\s*\d+[.、]?\s")

errors: list[str] = []
warnings: list[str] = []


def check_required() -> None:
    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            errors.append(f"缺少必需文件：{rel}")


def check_frontmatter() -> None:
    p = ROOT / "SKILL.md"
    if not p.exists():
        return
    raw = p.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if not m:
        errors.append("SKILL.md 缺少 YAML frontmatter")
        return
    fm = m.group(1)
    for key in ("name:", "description:"):
        if key not in fm:
            errors.append(f"SKILL.md frontmatter 缺少 {key[:-1]}")
    desc = re.search(r"^description:\s*(.+)$", fm, re.M)
    if desc and len(desc.group(1)) < 40:
        warnings.append("description 偏短，可能难以被正确触发")


def check_budget() -> None:
    p = ROOT / "SKILL.md"
    if not p.exists():
        return
    size = p.stat().st_size
    if size > SKILL_BUDGET_BYTES:
        errors.append(
            f"SKILL.md 体积 {size} 字节，超过预算 {SKILL_BUDGET_BYTES}；"
            "把细节移到 references/"
        )
    lines = p.read_text(encoding="utf-8").count("\n") + 1
    if lines > 200:
        warnings.append(f"SKILL.md 有 {lines} 行，建议压到 200 行内")


def _section_body(text: str, keyword: str) -> str:
    """取含 keyword 的标题行之后的正文，到下一个标题为止。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if keyword in ln and (s.startswith("#") or s.startswith("【")):
            start = i + 1
            break
    if start is None:
        return ""
    body: list[str] = []
    for ln in lines[start:]:
        s = ln.lstrip()
        if s.startswith("#") or s.startswith("【"):
            break
        body.append(ln)
    return "\n".join(body)


def count_numbered(text: str, keyword: str) -> int:
    return sum(1 for ln in _section_body(text, keyword).splitlines() if NUMBERED.match(ln))


def check_content() -> None:
    """正文关键块是否还在。这是给「压缩文档时整节消失」兜底的。"""
    checked = 0
    for rel, specs in CONTENT_SPECS.items():
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for label, pattern in specs:
            checked += 1
            if not re.search(pattern, text, re.M):
                errors.append(f"{rel} 缺少「{label}」，对应步骤会静默失效")
    print(f"  正文关键块 {checked} 项")


def check_entries_agree() -> None:
    """三份入口的条目数必须一致，否则等于两份互相矛盾的规则。"""
    texts: dict[str, str] = {}
    for rel in ("SKILL.md", "AGENTS.md", "prompts/standalone.md"):
        p = ROOT / rel
        if p.exists():
            texts[rel] = p.read_text(encoding="utf-8")

    for rel, text in texts.items():
        n = count_numbered(text, "条原则")
        if n != PRINCIPLE_COUNT:
            errors.append(f"{rel} 有 {n} 条原则，约定 {PRINCIPLE_COUNT} 条（对齐 SKILL.md）")

    rules = {rel: count_numbered(t, "硬约束") for rel, t in texts.items() if rel != "prompts/standalone.md"}
    if len(set(rules.values())) > 1:
        detail = "、".join(f"{k} {v} 条" for k, v in rules.items())
        errors.append(f"硬约束条数不一致：{detail}；{HARD_RULE_COUNT} 条为准")
    elif rules and next(iter(rules.values())) != HARD_RULE_COUNT:
        errors.append(f"硬约束应为 {HARD_RULE_COUNT} 条，实际 {next(iter(rules.values()))} 条")
    print(f"  入口一致性：原则 {PRINCIPLE_COUNT} 条 / 硬约束 {HARD_RULE_COUNT} 条")


def check_local_refs() -> None:
    """正文里用反引号写出的相对路径必须存在。"""
    checked = 0
    for rel in ("SKILL.md", "AGENTS.md", "prompts/standalone.md", "prompts/profile-interview.md",
                "prompts/self-interview.md", "references/judge.md", "references/compose.md",
                "references/style-guide.md", "references/profile.md", "references/self.md",
                "references/stages.md", "references/routes.md"):
        p = ROOT / rel
        if not p.exists():
            continue
        for m in LOCAL_REF.finditer(p.read_text(encoding="utf-8")):
            target = m.group(1)
            checked += 1
            if not (ROOT / target).exists():
                errors.append(f"{rel} 引用了不存在的文件：{target}")
    print(f"  正文路径引用 {checked} 个")

def check_sample_style() -> None:
    """临场取样冒烟：小样本只用禁用项，不接管长度；禁用项要真的拦得住。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import style_tool  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        errors.append(f"style_tool.py 无法导入：{exc}")
        return

    msgs = ["行", "咋了", "先这样 睡了啊", "出来吃个饭？我请", "别提了 今天累成狗"]
    card = {"small_sample": True, "metrics": style_tool.compute(msgs),
            "strategy": {"avoid": style_tool.infer_avoid(msgs)}}

    ok = style_tool.check("下周六开幕 我订两张", card, "minimal")
    if not ok["ok"]:
        errors.append(f"临场取样冒烟失败：正常短句被小样本卡误拦 {ok['problems']}")

    # 小样本的 p50 是这次对话的状态，不该变成 20 字句的上限依据
    long = style_tool.check("下周六我没问题 你定个时间 我都可以的", card, "minimal")
    if long["ok"]:
        errors.append("临场取样冒烟失败：小样本卡接管了长度上限")

    haha = style_tool.check("哈哈哈 行", card, "minimal")
    if haha["ok"]:
        errors.append("临场取样冒烟失败：avoid 里的「不用哈哈」没有生效")

    print("  临场取样冒烟：小样本只出禁用项，长度走绝对档，禁用项可拦")


def check_routes() -> None:
    """routes.md 里引用的每个 kb 路径都必须真实存在。断链比没有路由更糟。"""
    p = ROOT / "references" / "routes.md"
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    refs = set(re.findall(r"`((?:knowledge|practical)/[^`]+\.md)`", text))
    if not refs:
        warnings.append("routes.md 里没有识别到知识库引用，检查格式是否为反引号包裹的相对路径")
    for rel in sorted(refs):
        if not (ROOT / "references" / "kb" / rel).exists():
            errors.append(f"routes.md 引用了不存在的文件：{rel}")
    print(f"  路由引用 {len(refs)} 个，缺失 {sum(1 for r in refs if not (ROOT / 'references' / 'kb' / r).exists())} 个")


def check_kb() -> None:
    kb = ROOT / "references" / "kb"
    if not kb.exists():
        errors.append("缺少 references/kb/")
        return
    docs = sorted(kb.rglob("*.md"))
    if len(docs) < KB_MIN_DOCS:
        errors.append(f"知识库只有 {len(docs)} 篇，少于预期的 {KB_MIN_DOCS} 篇")
    for sub in ("knowledge", "practical"):
        if not (kb / sub).is_dir():
            errors.append(f"知识库缺少 {sub}/ 子目录（相对链接会断）")
    total = sum(d.stat().st_size for d in docs)
    print(f"  知识库 {len(docs)} 篇，{total / 1024:.0f} KB")


def check_style_tool() -> None:
    """冒烟测试：脚本能导入，正向放行、反向拦截。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import style_tool  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        errors.append(f"style_tool.py 无法导入：{exc}")
        return

    good = style_tool.check("下周六开幕 我订两张", None, "minimal")
    if not good["ok"]:
        errors.append(f"冒烟测试失败：正常短句被判不合格 {good['problems']}")

    bad = style_tool.check(
        "我理解你的感受，建议你先冷静一下，等她想通了自然会来找你。", None, "substantive")
    if bad["ok"]:
        errors.append("冒烟测试失败：AI 味长句未被拦截")
    print(f"  冒烟测试：正常句通过={good['ok']}，AI 味句拦截={not bad['ok']}")


def check_profile() -> None:
    """档案冒烟：建档 → 录入 → 取摘要，并确认摘要没有超出预算。"""
    import contextlib
    import io
    import tempfile

    tmp = tempfile.mkdtemp(prefix="love-reply-validate-")
    old = os.environ.get("LOVE_REPLY_HOME")
    os.environ["LOVE_REPLY_HOME"] = tmp
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import profile_tool
        with contextlib.redirect_stdout(io.StringIO()):
            profile_tool.main(["init", "--slot", "ci", "--alias", "她", "--stage", "couple_early"])
            profile_tool.main(["add", "--slot", "ci", "--kind", "landmine",
                               "--text", "她说累的时候别讲道理"])
            profile_tool.main(["add", "--slot", "ci", "--kind", "read",
                               "--text", "她最近很累，可能不想说话", "--confidence", "low"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            profile_tool.main(["brief", "--slot", "ci", "--query", "她说今天好累"])
        out = buf.getvalue().strip()
        if "雷区" not in out:
            errors.append("档案冒烟失败：brief 没有带出雷区")
        if "认知?[低]" not in out:
            errors.append("档案冒烟失败：低置信认知没有标记问号")
        if len(out.strip()) > profile_tool.BRIEF_TOTAL_CHARS + 40:
            errors.append(f"档案冒烟失败：brief 输出 {len(out.strip())} 字，超出预算")
        print(f"  档案冒烟：brief {len(out.strip())} 字，雷区与低置信标记正常")
    except SystemExit as exc:  # 子命令异常退出
        errors.append(f"档案冒烟失败：命令退出码 {exc.code}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"profile_tool.py 无法运行：{exc}")
    finally:
        if old is None:
            os.environ.pop("LOVE_REPLY_HOME", None)
        else:
            os.environ["LOVE_REPLY_HOME"] = old


def check_self_and_gate() -> None:
    """自我档案与闸门冒烟：底线要拦得住，阶段禁止的策略也要拦得住。"""
    import contextlib
    import io
    import tempfile

    tmp = tempfile.mkdtemp(prefix="love-reply-self-")
    old = os.environ.get("LOVE_REPLY_HOME")
    os.environ["LOVE_REPLY_HOME"] = tmp
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import profile_tool
        with contextlib.redirect_stdout(io.StringIO()):
            profile_tool.main(["self", "init"])
            profile_tool.main(["self", "add", "--kind", "limit", "--text", "不接受异地",
                               "--forbid", "搬过去"])
            profile_tool.main(["init", "--slot", "ci", "--stage", "repairing"])
            profile_tool.main(["goal", "add", "--slot", "ci", "--kind", "advance",
                               "--hard", "--text", "三个月内明确关系"])

        hit = profile_tool.guard("我下个月搬过去", profile_tool.load_self(),
                                 profile_tool.load("ci"), "advance", "repairing")
        if hit["ok"]:
            errors.append("闸门冒烟失败：踩底线且阶段禁止的候选未被拦截")

        ok = profile_tool.guard("是我没安排好", profile_tool.load_self(),
                                profile_tool.load("ci"), "repair", "repairing")
        if not ok["ok"]:
            errors.append(f"闸门冒烟失败：合规候选被误拦 {ok['problems']}")

        with contextlib.redirect_stdout(io.StringIO()):
            profile_tool.main(["brief", "--slot", "ci", "--query", "她说累了"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            profile_tool.main(["brief", "--slot", "ci", "--query", "她说累了"])
        out = buf.getvalue()
        if "[我]" not in out or "目标!" not in out:
            errors.append("自我档案冒烟失败：brief 没有带出自我段或硬目标标记")
        if "[阶段 " not in out or "可用 " not in out:
            errors.append("自我档案冒烟失败：brief 没有带出阶段卡（策略白名单与上限）")

        # verify 一次要能同时看见两道闸门的结果，否则它只是把两次调用换了个名字
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = profile_tool.main([
                "verify", "--slot", "ci",
                "--candidate", "minimal:是我没安排好",
                "--candidate", "advance:下周末一起出去玩吧",
                "--candidate", "repair:上次是我忘了，明天我自己去拿。",
            ])
        v = json.loads(buf.getvalue())
        rows = v["candidates"]
        if rows[0]["verdict"] != "pass":
            errors.append(f"verify 冒烟失败：合规候选被判 {rows[0]['verdict']} {rows[0]['problems']}")
        if rows[1]["verdict"] != "fail":
            errors.append("verify 冒烟失败：修复期的 advance 候选未被拦")
        if not any("表达" in p for r in rows for p in r["problems"]):
            errors.append("verify 冒烟失败：没有合并表达闸门的结论")
        if code == 0 and any(r["verdict"] == "fail" for r in rows):
            errors.append("verify 冒烟失败：有 fail 却返回 0")
        print(f"  闸门冒烟：底线拦截、阶段闸门、自我段、批量校验均正常（brief {len(out.strip())} 字）")
    except SystemExit as exc:
        errors.append(f"自我档案冒烟失败：命令退出码 {exc.code}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"自我档案冒烟失败：{exc}")
    finally:
        if old is None:
            os.environ.pop("LOVE_REPLY_HOME", None)
        else:
            os.environ["LOVE_REPLY_HOME"] = old


def check_gitignore() -> None:
    p = ROOT / ".gitignore"
    if not p.exists():
        errors.append("缺少 .gitignore，个人数据可能被提交")
        return
    if "data/" not in p.read_text(encoding="utf-8"):
        errors.append(".gitignore 未排除 data/，风格卡有泄露风险")


def main() -> int:
    print("love-reply 完整性检查")
    print(f"  根目录：{ROOT}")
    check_required()
    check_frontmatter()
    check_budget()
    check_content()
    check_entries_agree()
    check_local_refs()
    check_sample_style()
    check_routes()
    check_kb()
    check_style_tool()
    check_profile()
    check_self_and_gate()
    check_gitignore()

    for w in warnings:
        print(f"  [警告] {w}")
    for e in errors:
        print(f"  [错误] {e}")

    if errors:
        print(f"结果：失败（{len(errors)} 个错误，{len(warnings)} 个警告）")
        return 1
    if warnings:
        print(f"结果：通过，有 {len(warnings)} 个警告")
        return 2
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
