"""常量与元数据：类别定义、阶段闸门、字数预算、画像拦截词表。

这个模块只放数据，不 import 其它层，避免循环依赖。所有其它模块都从这里取常量。
"""
from __future__ import annotations

import re

KINDS = ("fact", "read", "unknown", "landmine", "soother", "promise", "event")
PREFIX = {
    "fact": "f", "read": "r", "unknown": "u", "landmine": "l",
    "soother": "s", "promise": "p", "event": "t",
}
LABEL = {
    "fact": "事实", "read": "认知", "unknown": "未知", "landmine": "雷区",
    "soother": "安抚器", "promise": "承诺", "event": "事件",
}
KEY = {
    "fact": "facts", "read": "reads", "unknown": "unknowns", "landmine": "landmines",
    "soother": "soothers", "promise": "promises", "event": "timeline",
}
# 检索权重：雷区与承诺最影响候选，权重最高
WEIGHT = {
    "landmine": 1.6, "promise": 1.4, "soother": 1.3,
    "fact": 1.2, "read": 1.0, "event": 0.9, "unknown": 0.7,
}
CONFIDENCE = ("high", "mid", "low")

BRIEF_MAX_CHARS = 380
BRIEF_ITEM_CHARS = 34
BRIEF_MAX_ITEMS = 8

# 合并后的总预算。自我段单独封顶，避免「我」把「她」挤出去。
BRIEF_TOTAL_CHARS = 520
BRIEF_SELF_CHARS = 170

# ---------------------------------------------------------------- 自我档案

SELF_KINDS = ("trait", "flaw", "limit", "capacity", "value", "voice")
SELF_PREFIX = {"trait": "t", "flaw": "f", "limit": "m",
               "capacity": "c", "value": "v", "voice": "o"}
SELF_LABEL = {"trait": "我", "flaw": "短板", "limit": "底线",
              "capacity": "能兑现", "value": "看重", "voice": "说话"}
# 只有这三类会直接拦截候选文本
SELF_GUARDING = ("limit", "flaw")

# ---------------------------------------------------------------- 关系目标

GOAL_KINDS = ("advance", "hold", "repair", "exit", "understand")
GOAL_LABEL = {"advance": "推进", "hold": "稳住", "repair": "修复",
              "exit": "收尾", "understand": "看清"}
HORIZONS = ("now", "season", "long")
HORIZON_LABEL = {"now": "这次", "season": "本阶段", "long": "长期"}

# ---------------------------------------------------------------- 阶段闸门

# 每个阶段允许、有条件允许、禁止的策略。allow/deny 是硬闸门，
# conditional 表示「可以，但要满足该阶段的前置条件」。
# detail 是细节密度：一句话里该给多少具体信息。
# 修复期细节要求低不是为了省事——细节在修复期会被当成辩解材料。
STAGE = {
    "stranger": {
        "task": "让她愿意继续回你，不提任何要求",
        "allow": ["minimal", "care"],
        "conditional": ["substantive"],
        "deny": ["advance", "repair", "hold"],
        "detail": "低", "max_chars": 24,
        "trap": "自我介绍式长段、查户口、连发追问、过早表态",
    },
    "warming": {
        "task": "把「有来有回」变成「见过面」，只推半步",
        "allow": ["minimal", "care", "substantive"],
        "conditional": ["advance"],
        "deny": ["repair", "hold"],
        # 「只推半步」的机械判据：邀约必须带退路，否则她拒绝的成本太高
        "advance_softener": ("有空", "方便", "要是", "如果", "不想", "看你想",
                             "随你", "不勉强", "看情况"),
        "detail": "中", "max_chars": 34,
        "trap": "把闲聊当信号、一次性推太满、给方案却没给退路",
    },
    "dating": {
        "task": "确认她愿不愿意继续，节奏由她定",
        "allow": ["minimal", "substantive", "advance"],
        "conditional": ["care", "repair"],
        "deny": ["hold"],
        "detail": "中高", "max_chars": 40,
        "trap": "用下一次邀约测试她、把不确定说成确定、过度解读已读不回",
    },
    "couple_early": {
        "task": "把磨合期的分歧说清楚，不攒着",
        "allow": ["minimal", "substantive", "advance", "care", "repair"],
        "conditional": ["hold"],
        "deny": [],
        "detail": "高", "max_chars": 60,
        "trap": "为了不吵而回避、翻旧账、用分手当筹码",
    },
    "couple_stable": {
        "task": "维持日常，把注意力放在她说过的事上",
        "allow": ["minimal", "substantive", "care", "repair", "hold"],
        "conditional": ["advance"],
        "deny": [],
        "detail": "高", "max_chars": 60,
        "trap": "只回情绪不接具体事、把稳定当成不用经营、仪式感替代日常",
    },
    "repairing": {
        "task": "先让她确认你听懂了，再谈事实",
        "allow": ["hold", "repair", "minimal", "care"],
        "conditional": ["substantive"],
        "deny": ["advance"],
        "detail": "低", "max_chars": 34,
        "trap": "解释动机、罗列细节自证、追加新承诺、逼她当场表态",
    },
}

# ---------------------------------------------------------------- 守门

STRATEGIES = ("minimal", "care", "substantive", "advance", "repair", "hold")

# danger >= 7 时不许出现的两种：邀约（advance）和给方案（substantive）。
# 稳住 = minimal / care，补救 = repair，留白 = hold，这三种才是这个阶段该说的。
DANGER_DENY = ("advance", "substantive")

# 默认画像的措辞拦截。只拦「怎么说」，不判断「她怎么想」，
# 不改变 danger 打分。默认先验只做这一件事：吃软不吃硬、慢热别催、
# 泛夸没用要具体、先复述再回应。有真实档案时，档案里的 landmine 优先于这里。
# 详见 references/persona.md。
#
# 分两层，用正则而非子串词表——中文变体太多（「你真好」「你对我真好」
# 「你对我可真好」），穷举词表会漏。
PERSONA_HARD = [
    # 质问 / 反问：吃软不吃硬，这种话会让她关上
    (re.compile(r"你(到底|究竟|又|什么意思|烦不烦|闹够了没)"), "质问反问"),
    (re.compile(r"(随便你吧|别闹了|爱怎样怎样|你爱怎么想怎么想)"), "质问反问"),
    # 催表态：慢热、回避冲突，逼她当场表态是往枪口上撞
    (re.compile(r"(给(个|句|我)|要个|现在|今天|到底)[就都]?(给(个|句|我)|必须)?(准话|痛快话|说法|说清楚)"), "催表态"),
    (re.compile(r"(到底是分还是合|要不要在一起)"), "催表态"),
]
PERSONA_SOFT = [
    # 泛夸：她觉得很套路，要具体不要抽象。「你对我可真好」这种叠修饰也要认。
    (re.compile(r"你(对我)?(可|真|实在|太)+(好|棒|厉害|重要|温柔|善解人意)"), "泛夸无具体"),
    (re.compile(r"你是(最好|最棒|最特别|最重要)的"), "泛夸无具体"),
    # 讲道理压情绪：她情绪起来时，讲道理等于否定她的感受
    (re.compile(r"(你应该|你想想|冷静一点|别激动|你要理性)"), "讲道理压情绪"),
    # 讨回应/催回复：她遇压力会转移、很少主动，连发追问只会让她彻底消失。
    # 这是软提示不是硬拦——真有事「看到回我一下」偶尔必要，但默认别这么写。
    (re.compile(r"(怎么不回|是不是生(气|我)|看到回|回复我|为什么不理|你人呢|在不在)"), "讨回应催回复"),
]

# 每类软提示各配一句人话，别让「讨回应」挂上「泛夸」的提示语。
PERSONA_SOFT_HINT = {
    "泛夸无具体": "她更吃具体的，不是这种空话",
    "讲道理压情绪": "她情绪起来时，讲道理等于否定她的感受",
    "讨回应催回复": "她遇压力会转移，追问只会让她消失；给她空间，别要她立刻回应",
}

# 整条回复的预算：判断一句 + 三条候选 + 结尾一句 ≤120 字，这是 SKILL.md 的承诺。
# 以前它只活在那句话里，没有任何落点；有卡时三档上限相加能到 100 字，
# 再加判断和结尾必然爆。这里把「留给候选的那部分」定死，才谈得上执行。
OUTPUT_BUDGET = 120
OVERHEAD = 50  # 判断句 + 选哪条那句，各按 25 字预留
CANDIDATE_BUDGET = OUTPUT_BUDGET - OVERHEAD

# 续写：对方已经回了一句，这一轮只给一句。
# 第二轮再摆三条，等于把「挑一条」的成本又推回给用户一次，节奏就断了。
ROUND_TWO_TEXT_BUDGET = 60

# 从她这一句里判「她是在收、在敷衍、还是接住了」。
# 词表故意小：判错的代价不对称——把「你忙吧」当邀请去追，比少说一句贵得多。
WITHDRAW_MARKS = ("你忙", "算了", "没事", "不用", "再说", "先这样", "不聊", "睡了", "晚安了", "拜拜", "改天")
EMPTY_MARKS = ("哦", "嗯", "好", "行", "随便", "呵呵", "额", "噢", "喔", "好的", "嗯嗯", "行吧", "都可以", "都行")
# 她开始商量细节，就是接住了。这一档只用来「允许往前走一步」，不靠它放行任何风险。
ENGAGED_MARKS = ("几点", "哪儿", "哪里", "哪家", "哪个", "怎么", "那周", "好啊", "好呀", "行啊", "可以", "你说")
