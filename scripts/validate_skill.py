#!/usr/bin/env python3
"""完整性自检：文件是否齐、路由是否可达、主文件是否超预算。

    python scripts/validate_skill.py

退出码 0 通过，1 有硬错误，2 只有警告。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = [
    "SKILL.md",
    "README.md",
    "LICENSE",
    "NOTICE.md",
    "references/judge.md",
    "references/compose.md",
    "references/style-guide.md",
    "references/routes.md",
    "scripts/style_tool.py",
    "licenses/goutoujunshi-LICENSE",
]

# 主文件太长会挤占对话上下文，这是硬预算
SKILL_BUDGET_BYTES = 12_000
KB_MIN_DOCS = 40

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
    check_routes()
    check_kb()
    check_style_tool()
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
