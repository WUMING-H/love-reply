"""存储与检索：档案的读写、条目 ID、字级相似度召回。

这一层只依赖 constants 和标准库，不 import 命令层，是无副作用的纯逻辑。
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from .constants import KEY, PREFIX, WEIGHT


# ---------------------------------------------------------------- 存储

def home() -> Path:
    env = os.environ.get("LOVE_REPLY_HOME")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent.parent.parent / "data"


def profile_path(slot: str) -> Path:
    return home() / "profile" / f"{slot}.json"


def self_path() -> Path:
    return home() / "self.json"


def empty(slot: str) -> dict:
    return {
        "slot": slot,
        "version": 1,
        "updated_at": now(),
        "person": {"alias": "她", "stage": "warming", "since": "", "basics": {}},
        "facts": [], "reads": [], "unknowns": [],
        "landmines": [], "soothers": [], "promises": [], "timeline": [],
        "pitfalls": [], "goals": [],
    }


def empty_self() -> dict:
    return {"version": 1, "updated_at": now(), "person": {"alias": "我"},
            "items": []}


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


def load_self(required: bool = False) -> dict | None:
    p = self_path()
    if not p.exists():
        if required:
            raise SystemExit(f"自我档案不存在：{p}\n先跑 self init。")
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"自我档案 JSON 损坏：{p}（{exc}）")


def save_self(data: dict) -> Path:
    p = self_path()
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


def item_tags(item: dict) -> list[str]:
    """兼容两种写法：老数据的 `tag` 字符串，新数据的 `tags` 列表。"""
    t = item.get("tags")
    if isinstance(t, list):
        return [x for x in t if x]
    if isinstance(t, str) and t:
        return [t]
    old = item.get("tag")
    return [old] if isinstance(old, str) and old else []


def score_entry(query: str, text: str, tags: list[str], weight: float) -> float:
    """字级相似度为主、双字词为辅。

    纯双字重叠会把「她说今天好累」和「她说生日」判成相关，因为共享「她说」。
    字级 Dice 对实词更敏感，也天然惩罚长度不匹配。

    tag 和正文一起参与匹配：用户提问是转述，档案存的是原话，两条中文句子
    只要换了说法就几乎不共字。「想给她买点水果」和「她不吃芒果」共享 0 个字，
    再怎么调权重也召不回。tag 是唯一能在不上向量检索的前提下补这个缺口的
    东西——它由录入的人自己写，可解释、可修改。
    """
    q = content_chars(query)
    joined = text + " " + " ".join(tags)
    e = content_chars(joined)
    if not q or not e:
        return 0.0
    # 标签原样出现在提问里，是比字面重合更强的信号：「想给她买点水果」和
    # 「她不吃芒果」一个字都不共，但如果录入时标了「水果」，就该命中。
    # 要求标签至少两个字——「吃」「班」这种单字标签挂上去等于没有标签。
    tag_hit = any(len(t) >= 2 and t in query for t in tags)
    # 只共享一个字通常是巧合（「她说今天好累」和「她说生日」只共享「她说」），
    # 宁可不给，也不要往上下文里塞噪音。
    if not tag_hit and len(q & e) < 2 and len(q) > 1:
        return 0.0
    char_sim = dice(q, e)
    gram_sim = dice(bigrams(query), bigrams(joined))
    score = (0.65 * char_sim + 0.35 * gram_sim) * weight
    if tag_hit:
        score = max(score, 0.55 * weight)
    return round(score, 4)


def entries(data: dict) -> list[tuple[str, dict, str]]:
    """(kind, item, 检索文本)"""
    out = []
    for item in data.get("facts", []):
        out.append(("fact", item, item["text"]))
    for item in data.get("reads", []):
        out.append(("read", item, f"{' '.join(item_tags(item))} {item['text']}"))
    for item in data.get("landmines", []):
        out.append(("landmine", item, f"{' '.join(item_tags(item))} {item['text']}"))
    for item in data.get("soothers", []):
        out.append(("soother", item, f"{' '.join(item_tags(item))} {item['text']}"))
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
        s = score_entry(query, text, item_tags(item), WEIGHT.get(kind, 1.0))
        if s >= MIN_SCORE:
            scored.append((round(s, 3), kind, item, text))
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]
