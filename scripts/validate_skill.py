#!/usr/bin/env python3
"""完整性自检：文件是否齐、路由是否可达、主文件是否超预算。

    python scripts/validate_skill.py

退出码 0 通过，1 有硬错误，2 只有警告。
"""

from __future__ import annotations

import json
import os
import re
import shutil
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
    "references/persona-isfp-cancer.md",
    "references/stages.md",
    "references/routes.md",
    "prompts/standalone.md",
    "prompts/profile-interview.md",
    "prompts/self-interview.md",
    "scripts/style_tool.py",
    "scripts/profile_tool.py",
    "scripts/eval_skill.py",
    "scripts/kb_route.py",
    "references/routes.json",
    "scripts/blind_test.py",
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
        ("点选记录入口", r"feedback --slot"),
        ("偏好不改闸门", r"只影响排序，不改闸门"),
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
        ("点选记录入口", r"feedback --slot"),
        ("偏好不改闸门", r"只影响排序，不改闸门"),
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

    # 冷启动安全默认里明写「不用叠字」，无卡时也该拦。这条曾经漏放——
    # AVOID_PATTERNS 只活在 infer_avoid 生成的 avoid 里，无卡时 strategy={}，
    # banned 根本没有它，「哈哈哈哈哈」「整整整整」全放行。
    dup = style_tool.check("我循环了整整整整一年", None, "care")
    if dup["ok"]:
        errors.append("冒烟测试失败：无卡时叠字「整整整整」未被拦截（安全默认失效）")
    # 反过来，「哈哈」两个字是日常说法，无卡时不能误伤。
    normal_haha = style_tool.check("我也笑了 哈哈", None, "care")
    if not normal_haha["ok"]:
        errors.append(f"冒烟测试失败：无卡时日常「哈哈」被误伤 {normal_haha['problems']}")
    print(f"  冒烟测试：正常句通过={good['ok']}，AI 味句拦截={not bad['ok']}，"
          f"无卡叠字拦截={not dup['ok']}")


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


def check_recall() -> None:
    """召回冒烟：换个说法也要命中 tag，常驻事实不靠检索。

    这两条是对着真实失效写的：录入「她不吃芒果」，问「想给她买点水果」召回 0 条，
    因为两条中文句子一个字都不共。事实录了等于没录。
    """
    import contextlib
    import io
    import tempfile

    tmp = tempfile.mkdtemp(prefix="love-reply-recall-")
    old = os.environ.get("LOVE_REPLY_HOME")
    os.environ["LOVE_REPLY_HOME"] = tmp
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import profile_tool
        with contextlib.redirect_stdout(io.StringIO()):
            profile_tool.main(["init", "--slot", "rc", "--stage", "couple_early"])
            profile_tool.main(["add", "--slot", "rc", "--kind", "fact",
                               "--text", "她不吃芒果", "--tag", "芒果", "水果", "过敏",
                               "--core"])
            profile_tool.main(["add", "--slot", "rc", "--kind", "fact",
                               "--text", "她周三有夜班 十点才下", "--tag", "下班", "班表"])

        def brief(query: str) -> str:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                profile_tool.main(["brief", "--slot", "rc", "--query", query])
            return buf.getvalue()

        if "芒果" not in brief("想给她买点水果"):
            errors.append("召回冒烟失败：换说法提问召不回打了 tag 的事实")
        if "夜班" not in brief("她今天几点下班"):
            errors.append("召回冒烟失败：tag 原样出现在提问里也没有命中")
        # 无关的问题不该把「夜班」也拖进来，否则等于没做检索
        if "夜班" in brief("想给她买点水果"):
            errors.append("召回冒烟失败：无关事实被错误带出（检索变成了全量注入）")
        print("  召回冒烟：tag 换说法命中、无关事实不入、常驻事实恒带")
    except SystemExit as exc:
        errors.append(f"召回冒烟失败：命令退出码 {exc.code}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"召回冒烟失败：{exc}")
    finally:
        if old is None:
            os.environ.pop("LOVE_REPLY_HOME", None)
        else:
            os.environ["LOVE_REPLY_HOME"] = old


def check_feedback_loop() -> None:
    """反馈闭环冒烟：写了要有人读，读了不能改闸门。

    feedback.jsonl 曾经只写不读，没有任何代码碰它，等于一个假装在学习的功能。
    这里断言三件：五票之后 verify 带出偏好、票数不够时闭嘴、偏好不改变通过与否。
    """
    import contextlib
    import io
    import tempfile

    tmp = tempfile.mkdtemp(prefix="love-reply-fb-")
    old = os.environ.get("LOVE_REPLY_HOME")
    os.environ["LOVE_REPLY_HOME"] = tmp
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import profile_tool
        import style_tool

        def quiet(mod, argv) -> str:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                if mod is style_tool:
                    saved = sys.argv
                    sys.argv = ["style_tool.py"] + list(argv)
                    try:
                        mod.main()
                    finally:
                        sys.argv = saved
                else:
                    mod.main(argv)
            return buf.getvalue()

        quiet(profile_tool, ["init", "--slot", "fb", "--stage", "couple_early"])
        quiet(profile_tool, ["init", "--slot", "fb2", "--stage", "couple_early"])
        # 票数不够时必须闭嘴：三次里两次选 A，可能只是那天只有 A 能用
        for _ in range(2):
            quiet(style_tool, ["feedback", "--slot", "fb2", "--kind", "chosen",
                               "--strategy", "minimal", "--ai", "嗯 我到了"])
        if json.loads(quiet(profile_tool, ["prefs", "--slot", "fb2"]))["hint"]:
            errors.append("反馈冒烟失败：只有两票就给出了偏好结论")

        for _ in range(4):
            quiet(style_tool, ["feedback", "--slot", "fb", "--kind", "chosen",
                               "--strategy", "minimal", "--ai", "嗯 我到了"])
        quiet(style_tool, ["feedback", "--slot", "fb", "--kind", "chosen",
                           "--strategy", "care", "--ai", "先睡吧"])
        hint = json.loads(quiet(profile_tool, ["prefs", "--slot", "fb"]))["hint"]
        if "minimal" not in hint:
            errors.append("反馈冒烟失败：五票之后没有算出偏好，feedback 仍然是只写不读")
        # 偏好只排序不准入：修复期的 advance 该拦还是要拦
        out = json.loads(quiet(profile_tool, [
            "verify", "--slot", "fb", "--stage", "repairing",
            "--candidate", "advance:下周末一起出去玩吧"]))
        if out["candidates"][0]["verdict"] != "fail":
            errors.append("反馈冒烟失败：偏好把阶段闸门顶掉了（修复期放过了 advance）")
        if "habit" not in out:
            errors.append("反馈冒烟失败：verify 没有带出 habit")
        print("  反馈冒烟：五票出偏好、两票闭嘴、偏好不越闸门")
    except SystemExit as exc:
        errors.append(f"反馈冒烟失败：命令退出码 {exc.code}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"反馈冒烟失败：{exc}")
    finally:
        if old is None:
            os.environ.pop("LOVE_REPLY_HOME", None)
        else:
            os.environ["LOVE_REPLY_HOME"] = old


def check_blind_test() -> None:
    """盲测冒烟：表里不能有答案，认出率不能永远绿。

    这套东西唯一的价值在于「判的时候看不见答案」。如果 sheet.md 混进了
    mine/gen 字样，或者怎么答都通过，它就只是个仪式。这里断言四件：
    标签不泄漏、几乎没改写的条目被剔除、全认对判红、全选同一侧判作废。
    """
    import contextlib
    import io
    import tempfile

    sys.path.insert(0, str(ROOT / "scripts"))
    tmp = Path(tempfile.mkdtemp(prefix="love-reply-bt-"))
    cases = tmp / "cases.jsonl"
    rows = [{"id": f"t{i}", "context": "她：在吗", "mine": f"在 咋了{i}",
             "generated": f"在的，请问有什么事情吗{i}"} for i in range(10)]
    rows.append({"id": "dup", "mine": "在 咋了", "generated": "在 咋了"})
    cases.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                     encoding="utf-8")
    round_dir = tmp / "r1"

    try:
        import blind_test

        def run(argv) -> tuple[int, str]:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = blind_test.main(argv)
            return code, buf.getvalue()

        run(["make", "--in", str(cases), "--out", str(round_dir), "--seed", "5"])
        sheet = (round_dir / "sheet.md").read_text(encoding="utf-8")
        key = json.loads((round_dir / "key.json").read_text(encoding="utf-8"))
        if "mine" in sheet or "a_is" in sheet:
            errors.append("盲测冒烟失败：表格里带了答案标签，等于把答案写在卷面上")
        if key["n"] != 10 or not key["excluded"]:
            errors.append("盲测冒烟失败：几乎没改写的条目没被剔除（或条数算错）")

        right = ["A" if it["a_is"] == "mine" else "B" for it in key["items"]]
        code, _ = run(["score", "--round", str(round_dir), "--picks", ",".join(right)])
        if code != 1:
            errors.append("盲测冒烟失败：全认对了却没判红，认出率是个装饰")

        opposite = ["B" if p == "A" else "A" for p in right]
        half = right[:5] + opposite[5:]
        code, out = run(["score", "--round", str(round_dir), "--picks", ",".join(half), "--json"])
        summary = json.loads(out.strip().splitlines()[-1])
        if abs(summary["rate"] - 0.5) > 1e-9 or summary["code"] == 1:
            errors.append(f"盲测冒烟失败：一半认对的算出 {summary['rate']}，或仍判红")

        code, _ = run(["score", "--round", str(round_dir), "--picks", ",".join(["A"] * 10)])
        if code != 2:
            errors.append("盲测冒烟失败：全选同一侧没有判作废（位置偏好没兜住）")

        print("  盲测冒烟：表无答案、近似条目剔除、全对判红、单侧判作废")
    except SystemExit as exc:
        errors.append(f"盲测冒烟失败：命令退出码 {exc.code}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"盲测冒烟失败：{exc}")


def check_verify_hardening() -> None:
    """闸门自己的洞：这几条以前都是「正文承诺、脚本不查」。

    共同点是改坏了也不报错，只会安静放过一条本该死的话。所以每条都要有断言：
    空候选、没有阶段、三条同策略、全角冒号、danger≥7、120 字预算。
    """
    import contextlib
    import io
    import tempfile

    tmp = tempfile.mkdtemp(prefix="love-reply-hd-")
    old = os.environ.get("LOVE_REPLY_HOME")
    os.environ["LOVE_REPLY_HOME"] = tmp
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import profile_tool
        import style_tool

        def run_raw(argv) -> tuple[int, str]:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                try:
                    code = profile_tool.main(argv)
                except SystemExit as exc:  # argparse 的 choices 拒绝
                    code = exc.code if isinstance(exc.code, int) else 1
            return code, buf.getvalue()

        def run(argv) -> tuple[int, dict]:
            code, text = run_raw(argv)
            return code, json.loads(text)

        if style_tool.check("", None, "minimal")["ok"]:
            errors.append("闸门漏洞：空候选被判通过（模型某条生成失败会直接发出去）")

        if profile_tool.guard("周末出来散散心吧", {}, None, "advance", "couple_early", 7)["ok"]:
            errors.append("闸门漏洞：danger≥7 时邀约照样通过")
        if profile_tool.guard("我们坐下来把问题一条条理清楚", {}, None,
                              "substantive", "couple_early", 7)["ok"]:
            errors.append("闸门漏洞：danger≥7 时「给方案」照样通过（只拦了邀约）")
        if not profile_tool.guard("我在 你说", {}, None, "care", "couple_early", 7)["ok"]:
            errors.append("闸门漏洞：danger≥7 时把「稳住」也拦了，人就没话可说")

        c = profile_tool._parse_candidate("minimal：嗯 我知道了")
        if c["strategy"] != "minimal" or "minimal" in c["text"]:
            errors.append(f"闸门漏洞：全角冒号没归位，候选里带着前缀（{c}）")
        if profile_tool._parse_candidate("minmal:嗯")["strategy"] != "minimal":
            errors.append("闸门漏洞：拼错的策略名没有归位")

        # 没有阶段时，最危险的结果不是报错，是输出「可以直接输出」
        code, out = run(["verify", "--slot", "nosuch", "--candidate", "minimal:嗯 我知道了"])
        if code != 2 or out["stage_gate"] != "skipped" or "可以直接输出" in out["summary"]["next"]:
            errors.append("闸门漏洞：没有阶段时仍然宣称可以直接输出（阶段闸门静默消失）")

        code, out = run(["verify", "--stage", "couple_early",
                         "--candidate", "minimal:嗯 我知道了",
                         "--candidate", "minimal:好的 明白了",
                         "--candidate", "minimal:行 收到"])
        if code != 2 or not out["group_problems"]:
            errors.append("闸门漏洞：三条同一策略仍然算通过（正文要求策略必须不同）")

        code, out = run(["verify", "--stage", "couple_early",
                         "--candidate", "minimal:嗯 我在 你说 别急 慢慢来 不用赶时间",
                         "--candidate", "substantive:下周六下午两点我到楼下接你 顺便把上次那本书带给你 不用你跑一趟",
                         "--candidate", "advance:那明天下午我带杯咖啡过去找你 方便的话"])
        if not any("120" in p for p in out["group_problems"]):
            errors.append(f"闸门漏洞：三条合计 {out['total_chars']} 字超过 120 预算却没提示")

        # 档案是明文 JSON，README 明说可以直接改。改出一个拼错的阶段时，
        # 不能拿它当闸门依据，也不能悄悄退化成「没有闸门」还说通过。
        run_raw(["init", "--slot", "bad", "--stage", "warming"])
        bad = Path(tmp) / "profile" / "bad.json"
        data = json.loads(bad.read_text(encoding="utf-8"))
        data["person"]["stage"] = "coup_early"
        bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        code, text = run_raw(["verify", "--slot", "bad", "--candidate", "minimal:嗯 我知道了"])
        try:
            out = json.loads(text)
        except json.JSONDecodeError:
            out = None
        if out is None:
            errors.append("闸门漏洞：档案里拼错的阶段让 verify 崩了，连判定表都没出")
        elif out["stage_gate"] != "skipped" or code != 2:
            errors.append("闸门漏洞：档案里拼错的阶段被当成了闸门依据")

        # 只有一份档案时，默认槽位不该把人挡在「档案不存在」外面。
        # 单独开一个 home：上面那份 bad.json 会让「唯一的档案」变成坏阶段的，
        # 断言的就不是回退了。
        solo = tempfile.mkdtemp(prefix="love-reply-solo-")
        os.environ["LOVE_REPLY_HOME"] = solo
        run_raw(["init", "--slot", "warming", "--stage", "warming"])
        code, text = run_raw(["brief", "--query", "她说今天好累"])
        if code != 0 or "档案不存在" in text:
            errors.append("读路径没有收敛到唯一那份档案：只有一个 warming 档案时 brief 仍然报不存在")
        os.environ["LOVE_REPLY_HOME"] = tmp

        code, _ = run_raw(["init", "--slot", "zz", "--stage", "coup_early"])
        if code == 0:
            errors.append("init 接受了拼错的阶段名（其余命令都做了 choices）")

        print("  闸门硬化：空候选拦、无阶段降级、策略去重、冒号归一、危险阈值、字数预算、单档案回退")
    except SystemExit as exc:
        errors.append(f"闸门硬化冒烟失败：命令退出码 {exc.code}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"闸门硬化冒烟失败：{exc}")
    finally:
        if old is None:
            os.environ.pop("LOVE_REPLY_HOME", None)
        else:
            os.environ["LOVE_REPLY_HOME"] = old


def check_persona() -> None:
    """默认画像（ISFP + 巨蟹）的措辞拦截。

    只拦「怎么说」，不判断「她怎么想」、不改 danger。硬拦质问/催表态，
    软提示泛夸/讲道理。关键断言：硬拦要拦得住、软提示不误伤日常、人格标签不泄漏。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import profile_tool
    except Exception as exc:  # pragma: no cover
        errors.append(f"画像拦截无法导入：{exc}")
        return

    def problems(text: str, strategy: str = "care", stage: str = "couple_early") -> list[str]:
        return profile_tool.guard(text, None, None, strategy, stage, None)["problems"]

    def notes(text: str, strategy: str = "care", stage: str = "couple_early") -> list[str]:
        return profile_tool.guard(text, None, None, strategy, stage, None)["notes"]

    # 硬拦：质问反问、催表态。这些几乎总是错，踩「吃软不吃硬」。
    for bad in ("你到底想怎样", "别闹了", "你现在就给个准话", "到底是分还是合"):
        if not problems(bad):
            errors.append(f"画像硬拦失效：{bad!r} 该被拦却没拦")

    # 软提示：泛夸、讲道理压情绪。不拦（不阻塞），但要给提示。
    if not notes("你对我真好 还等我"):
        errors.append("画像软提示失效：「你对我真好」该给泛夸提示却没给")
    if not notes("你应该冷静一点"):
        errors.append("画像软提示失效：「你应该冷静」该给讲道理提示却没给")

    # 无误伤：日常真诚的话不能被画像误拦。
    for good in ("你记得我不吃香菜", "好想见你", "你帮了我大忙", "我想你"):
        if problems(good):
            errors.append(f"画像误伤：{good!r} 被当成了对抗/催表态")

    # 人格标签一个字都不许出现在 problems/notes 里——画像只影响「怎么说」，
    # 不朗读「ISFP」「巨蟹」，也不替她下判断。
    for txt in ("你什么意思", "你对我真好"):
        joined = " ".join(problems(txt) + notes(txt))
        if "ISFP" in joined or "巨蟹" in joined:
            errors.append(f"画像把人格标签泄漏进输出了：{joined}")

    # 无档案时 brief 要带画像要点。
    import contextlib
    import io
    import tempfile
    tmp = tempfile.mkdtemp(prefix="love-reply-persona-")
    old = os.environ.get("LOVE_REPLY_HOME")
    os.environ["LOVE_REPLY_HOME"] = tmp
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            profile_tool.main(["init", "--slot", "p", "--alias", "她", "--stage", "couple_early"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            profile_tool.main(["brief", "--slot", "p", "--query", "她说今天好累"])
        text = buf.getvalue()
        if "画像" not in text or "吃软不吃硬" not in text:
            errors.append("无档案时 brief 没有带出默认画像要点")
    finally:
        if old is None:
            os.environ.pop("LOVE_REPLY_HOME", None)
        else:
            os.environ["LOVE_REPLY_HOME"] = old

    print("  画像拦截：硬拦质问催表态、软提示泛夸讲道理、无误伤、标签不泄漏、无档案带画像")


def check_round_two() -> None:
    """续写：她回了一句之后的那一轮。

    这一轮最容易犯的错不是写得不好，是把它当成第一轮重来一次——再摆三条让她挑、
    把上一句换个说法又说一遍、她已经往回收了还在往前推。三种错都不会报错，
    只会显得没在听。
    """
    import contextlib
    import io
    import tempfile

    tmp = tempfile.mkdtemp(prefix="love-reply-r2-")
    old = os.environ.get("LOVE_REPLY_HOME")
    os.environ["LOVE_REPLY_HOME"] = tmp
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import profile_tool

        def run_raw(argv) -> tuple[int, str]:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                try:
                    code = profile_tool.main(argv)
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else 1
            return code, buf.getvalue()

        def run(argv) -> tuple[int, dict]:
            code, text = run_raw(argv)
            return code, json.loads(text)

        # 进退判错的方向要偏保守：把「你忙吧」当成邀约去追，比少说一句贵得多。
        for text, want in (("那你忙吧", "withdraw"), ("睡了 明天再说", "withdraw"),
                           ("嗯", "cold"), ("哦哦", "cold"), ("好的", "cold"),
                           ("好呀 那周六几点", "engaged"), ("我最近工作上一堆事 累" + "得不行", "engaged")):
            got = profile_tool.read_signal(text)[0]
            if got != want:
                errors.append(f"进退判错：「{text}」应为 {want}，实际 {got}")
        # 「哈哈哈」是在笑，不是敷衍。判成冷会让人对她唯一一次热络反应答得拘谨。
        if profile_tool.read_signal("哈哈哈")[0] == "cold":
            errors.append("进退判错：「哈哈哈」被判成敷衍")

        # 上一轮用 minimal：这样只有「她在收还在推」能拦住，不会和「连推」互相兜底。
        # 两条规则叠在同一个用例上，关掉其中一条测试照样绿——那种断言等于没有。
        base = ["verify", "--stage", "dating", "--then", "那你忙吧",
                "--prev", "minimal:行 你先忙"]

        code, out = run(base + ["--candidate", "advance:那周日下午吧"])
        if out["candidates"][0]["verdict"] != "fail" or code != 2:
            errors.append("续写漏洞：她已经在收（「你忙」），邀约照样通过")
        if out["signal"] != "withdraw" or not out["branch"]:
            errors.append("续写漏洞：没有判出她在收，或没给她收线后该怎么接")

        code, out = run(["verify", "--stage", "dating", "--then", "好呀 那周六几点",
                         "--prev", "advance:下周六有展 我订两张",
                         "--candidate", "advance:那我来接你"])
        if out["candidates"][0]["verdict"] != "fail":
            errors.append("续写漏洞：连着推两次 advance 照样通过")

        code, out = run(["verify", "--stage", "dating", "--then", "嗯",
                         "--prev", "care:听着就累 早点躺下",
                         "--candidate", "care:听着就累 早点睡吧"])
        if out["candidates"][0]["verdict"] != "fail":
            errors.append("续写漏洞：把上一句换个说法又说一遍，照样通过")

        # 三条策略各不相同、都不违规，唯一的问题只剩条数。否则「策略重复」
        # 会替「条数」兜底，关掉条数检查测试也照样绿。
        code, out = run(["verify", "--stage", "dating", "--then", "好呀 那周六几点",
                         "--prev", "advance:下周六有展 我订两张",
                         "--candidate", "minimal:两点", "--candidate", "care:你定吧",
                         "--candidate", "substantive:两点开始 我提前十分钟到"])
        if not out["group_problems"]:
            errors.append("续写漏洞：第二轮还是摆三条，没有拦")
        elif "续写只给一句" not in " ".join(out["group_problems"]):
            errors.append("续写漏洞：三条被拦了，但理由不是「第二轮只给一句」")

        code, out = run(["verify", "--stage", "dating", "--then", "好呀 那周六几点",
                         "--candidate", "minimal:两点 我提前到"])
        if not out["group_problems"] or code != 2:
            errors.append("续写漏洞：没给 --prev，查不了重复和连推，却照样放行")

        code, out = run(["verify", "--stage", "dating", "--then", "好呀 那周六几点",
                         "--prev", "advance:下周六有展 我订两张",
                         "--candidate", "minimal:两点 我提前到"])
        if code != 0 or out["round"] != 2 or out["candidates"][0]["verdict"] != "pass":
            errors.append("续写坏了：一条合格的第二轮回复都过不了闸")

        # 续写不再按三条的预算算，也不该被「三条重复」误伤
        if out["group_problems"]:
            errors.append("续写误判：单条续写被当成了「三条重复」")

        print("  续写冒烟：进退三档、收线后不推、连推拦、重复拦、单条约束、正常通过")
    finally:
        if old is None:
            os.environ.pop("LOVE_REPLY_HOME", None)
        else:
            os.environ["LOVE_REPLY_HOME"] = old
        shutil.rmtree(tmp, ignore_errors=True)


def check_kb_routes() -> None:
    """知识路由：43 篇里谁能到达、路径是否真实存在、表和数据是否一致。

    以前路由是一张 Markdown 表，模型自己看、自己去找。改文件名、写错路径、
    某个意图的入口被删光，都不会有人报错——只是少读一篇，而输出长得一样。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import kb_route

    data = kb_route.load()
    report = kb_route.audit()

    if report["missing"]:
        errors.append(f"路由指向不存在的知识文件：{'、'.join(report['missing'][:3])}")
    if report["orphans"]:
        errors.append("知识库有文件谁也到不了（进路由，或写进 exclude 说明理由）："
                      + "、".join(report["orphans"][:3]))
    if report["overlap"]:
        errors.append("同一篇知识被同时声明为可路由与不可路由："
                      + "、".join(report["overlap"][:3]))
    if report["dangling_refs"]:
        errors.append("参考入口指向不存在的文档或文档里没提到它：" + "；".join(report["dangling_refs"][:2]))
    if report["unreachable_intents"]:
        errors.append("有意图在任何阶段都路由不出篇目：" + "；".join(report["unreachable_intents"][:2]))

    # 表是派生物。两套不一致时，模型读到的是旧表，人维护的是新数据。
    doc_path = ROOT / "references" / "routes.md"
    doc = doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""
    if kb_route.BEGIN not in doc or kb_route.END not in doc:
        errors.append("routes.md 里没有生成块标记，无法和 routes.json 比对")
    else:
        cur = doc[doc.index(kb_route.BEGIN): doc.index(kb_route.END) + len(kb_route.END)] + "\n"
        if cur != kb_route.render():
            errors.append("routes.md 的表格块与 routes.json 不一致：跑 scripts/kb_route.py render")

    stages = ("", "stranger", "warming", "dating", "couple_early", "couple_stable", "repairing")
    checked = 0
    for intent in data["intents"]:
        for stage in stages:
            for danger in (None, 3, 8):
                out = kb_route.route(intent, stage, danger)
                checked += 1
                if not out["files"]:
                    errors.append(f"路由空洞：{intent} / {stage or '任意阶段'} / danger={danger} 没有篇目")
                    continue
                if out["count"] > data["max_files"]:
                    errors.append(f"路由超限：{intent} 给出 {out['count']} 篇，上限 {data['max_files']}")
                if len(set(out["files"])) != len(out["files"]):
                    errors.append(f"路由有重复篇目：{intent} / {stage or '任意阶段'}")
                for f in out["files"]:
                    if not (ROOT / f).exists():
                        errors.append(f"路由给出的路径不存在：{f}")

    # 危机是唯一会改变任务性质的 flag：读到它就只该剩一件事
    crisis = kb_route.route("vent", "couple_early", 8, ("危机",))
    if not crisis["stop"] or crisis["count"] != 1 or "17-" not in crisis["files"][0]:
        errors.append("危机 flag 没有收敛成「只读 17 号那篇、并停止给话术」")

    # 补进路由的材料必须真的取得到，否则只是从「躺平」变成「名义上可达」
    reachable: set[str] = set()
    for intent in data["intents"]:
        for stage in stages:
            reachable.update(kb_route.route(intent, stage, 5)["files"])
    for flag in data.get("flags", {}):
        reachable.update(kb_route.route("casual", "", None, (flag,))["files"])
    for kw in ("万能夸人", "废话文学", "聊天化被动为主动", "ChatLab", "长期记忆"):
        if not any(kw in f for f in reachable):
            errors.append(f"声称补进了路由，实际取不到：{kw}")

    print(f"  知识路由：{report['on_disk']} 篇 · 可路由 {report['declared']} · "
          f"仅参考 {report['reference_only']} · 排除 {report['excluded']} · 取路 {checked} 次")


def check_practical_tone() -> None:
    """知识库 practical 系列不许退回「话术库」形态。

    这批篇目最早是从参考材料转译来的，原文是「话术：××× 成品句 + 逻辑：×××
    解释」的堆砌，带 mindmap 包裹和「AI 生成」标注。模型读到成品句会倾向于
    照抄，产出一模一样的客套句——直接违反 SKILL.md「像他，不像 AI」的红线。
    2026-11 把它们全部转译成「原则 + 结构 + 何时用/何时不用」，这里守三件事：
    不出现 mindmap 包裹、不出现 AI 生成标注、不出现可直接复制的成品句。
    """
    import re
    prac = ROOT / "references" / "kb" / "practical"
    if not prac.exists():
        return
    # 成品句的判定：紧跟在「话术：」或「拒绝话术：」等标签后、且带具体内容。
    # 「实战话术编排器」的标题里带「话术」但内容是七策略原则，不在这里拦。
    script_pattern = re.compile(r"(?:话术|拒绝话术|主动话术|替代式拒绝)[：:]")
    for f in sorted(prac.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        name = f.name
        if "```mindmap" in text:
            errors.append(f"话术库残留（mindmap 包裹）：{name}")
        if "由 AI 生成" in text or "AI 生成" in text:
            errors.append(f"话术库残留（AI 生成标注）：{name}")
        # 成品句：排除标题行本身（# 开头）里的「话术」，只看正文里的「话术：」
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if script_pattern.search(line):
                errors.append(f"话术库残留（成品句「话术：」）：{name}")
                break

    print(f"  话术库转译：practical 目录已全部转为「原则 + 结构」形态，无成品句/标注残留")


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
    check_recall()
    check_feedback_loop()
    check_blind_test()
    check_verify_hardening()
    check_persona()
    check_round_two()
    check_kb_routes()
    check_practical_tone()
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
