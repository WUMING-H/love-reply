# love-reply

> 让 AI 用**你**的方式回消息。

粘贴一段中文聊天记录，给出三条可以直接复制发送的回复。

区别不在「写得像人」，而在**写得像你**——你的句长、你的标点习惯、你生气时的反应方式。

**[English](#english)** · 中文

---

## 它和别的「AI 回消息」不一样在哪

大部分同类工具在做一件事：让 AI 的回复「更自然、更懂情绪」。这条路的天花板很低，因为产出永远是一个**通用的好人**在说话，不是你。

这个项目多做了两件事：

**一、先判断，再写。** 七个固定问题一次判完：这句话是不是纯字面、真实意图是什么、危险程度 0–9、该不该给实质内容、最佳动作、对方需要什么、张力是否解除。不判断就写，等于猜。

**二、写完再过一道风格闸门。** 从你真实发过的消息里统计算出长度分布、句号率、emoji 密度，然后把候选改写成你会打出来的字，再按这些硬指标回查一遍。

第二条是关键。真人微信消息的中位数在 8–18 字，短句占四到七成；而 LLM 直接输出是 40–70 字、短句接近零。**这个差距比任何用词差异都明显**——只模仿词汇不模仿长度，写得再像也是另一个人。

---

## 怎么工作

```
输入（聊天记录）
 ├─ 1 归一化     拆角色、去昵称、分「事实 / 推测 / 未知」三栏
 ├─ 2 判断层     固定 7 问，一次调用，输出结构化判断
 ├─ 3 知识层     按「意图 × 关系阶段」检索 2–3 篇，不做全库注入
 ├─ 4 生成层     先锁目标，再出 3 条策略互异的候选
 ├─ 5 风格层     按人设槽位改写成「你会说的话」
 └─ 6 校验层     硬规则 + 风格指标，双闸门
      └→ 3 条候选 + 一句判断 + 一条「别做什么」
```

几个设计上的取舍：

- **知识只影响策略，不能出现在回复里。** 依恋理论、非暴力沟通这些词一个都不许进候选文本。验收标准：把知识删掉，候选应该一个字不变。
- **风格必须有硬指标。** 模型数不出「句号率 0.06」，让它估会给 0.3 这种瞎猜的数。所以度量层是纯代码统计，不调模型。
- **不微调小模型。** 几百条语料训出来是四不像，改一次要重训。风格卡改一个 JSON 就生效。

---

## 安装

```bash
git clone https://github.com/WUMING-H/love-reply.git

# WorkBuddy
cp -r love-reply ~/.workbuddy/skills/love-reply

# Claude Code（或任何读 SKILL.md 的宿主）
cp -r love-reply ~/.claude/skills/love-reply
```

Windows 也可以直接把目录放到 skills 目录下，或用目录联接指向别处。

数据目录默认：

| 平台 | 位置 |
|---|---|
| Windows（存在 `E:\project\WorkBuddy`） | `E:\project\WorkBuddy\skills\love-reply\data` |
| 其他 | `~/.love-reply` |

用环境变量 `LOVE_REPLY_HOME` 可以改到任意位置。`data/` 已在 `.gitignore` 里，不会进版本库。

---

## 用法

**直接回消息**

```
帮我回这条

她：你上次说的那个展，是这周还是下周
我：下周
她：哦
```

输出：

```
她这句是在问你记不记得，不是真问时间。你只回「下周」等于没接住。

1. 下周六开幕
2. 下周六开幕 下午两点有讲解 我订两张
3. 下周六 我过去接你 中午先吃饭

选 2。别问「你怎么了」，她不想解释。
```

**只想知道对方什么意思** — `他这句什么意思` + 粘贴，只给判断不给话术。

**润色自己的草稿** — `我想这么回，帮我改得像人话` + 你的草稿，跳过分析直接改。

---

## 风格卡：让它真的像你

没有风格卡也能用，但给的是「一个正常人会怎么回」；有了之后给的是「你会怎么回」。

```bash
# 一行一条，只放你自己发的消息，50-100 条起
python scripts/style_tool.py profile --file 我的消息.txt --slot couple_early

# 校验一条生成结果符不符合你的风格
python scripts/style_tool.py check --text "下周六开幕" --strategy minimal
```

`profile` 会算出长度分布、句号率、emoji 密度，并从「你从不做什么」反推禁用表——不出现 emoji 就写「不用 emoji」，不加句号就写「不加句号」。

**为什么反推禁用比正面描述有用：** 模型很难执行「你要幽默」，但很容易执行「不许出现 emoji」。前者是软引导，后者是硬拦截。

`check` 按策略分档卡长度：`minimal` 不该超过 16 字，`substantive` 天生更长。用同一把尺子会把「给具体时间方案」这类必要长句全拦掉。

**按关系分槽位**（`couple_early` / `couple_stable` / `friend` / `work`），不是为精细，是为防串味——对伴侣的撒娇语气拿去回同事会出事。

### 冷启动的五个问题

没有语料时，回答这几个就能建出可用的 v0：

1. 一般发几条？每条多长？
2. 句末加句号吗？
3. 用 emoji 吗？最常用哪两个？
4. 生气时变长（讲道理）还是变短（冷处理）？
5. 安慰人是先讲道理，还是先接情绪？

---

## 项目来源

这个项目是拼装出来的，不假装全部原创：

| 部分 | 来源 | 说明 |
|---|---|---|
| 七问判断协议 | [jev-chat/jev-chat-jarvis](https://github.com/jev-chat/jev-chat-jarvis)（MIT） | 借鉴其固定问题集的结构与动作枚举，判据按中文语境重写，未复制代码 |
| 43 篇知识库 | [shengjidaguai-china/goutoujunshi](https://github.com/shengjidaguai-china/goutoujunshi)（MIT） | **原样复用，未修改**，仅新增检索路由表。版权声明见 [NOTICE.md](NOTICE.md) |
| 风格层、校验器、路由表、六层编排 | 本项目 | 原创 |

知识库包含亲密关系心理学、沟通修复、边界与同意、法律安全转介等 43 篇中文材料。检索时只取 2–3 篇——塞满不是更准，是开始念经。

---

## 它不做什么

- **不给「TA 爱不爱你」打分。** 这是伪科学，会把人推向错误决策。
- **不抓聊天记录。** 不做无障碍读屏、不解析第三方 App 数据。粘贴一下的成本不到五秒，封号风险不值得。
- **不代发。** 自动回复看着省事，实际会让人失去对关系的真实判断。
- **不给操控性建议。** 不制造焦虑、不冷处理施压、不教人怎么「测试」对方。

命中跟踪、威胁、自伤、暴力内容时，停止给话术，只给求助渠道（见 `references/kb/knowledge/17`）。

---

## 许可

代码与文档：MIT，见 [LICENSE](LICENSE)。
第三方知识库：MIT，见 [licenses/goutoujunshi-LICENSE](licenses/goutoujunshi-LICENSE) 与 [NOTICE.md](NOTICE.md)。

---

<a name="english"></a>
## English

A skill for replying to Chinese chat messages. Paste a conversation, get three ready-to-send replies.

It is not about sounding human — it is about sounding like **you**.

Two things set it apart:

1. **Judge first.** Seven fixed questions are answered in one pass (literal vs subtext, true intent, danger level 0–9, whether substance is needed, best action, what the other person needs, whether tension is resolved). Most tools skip this and just generate.

2. **A style gate after generation.** Sentence length distribution, terminal-period rate, emoji density, and forbidden-word list are computed from the user's own past messages. Candidates are rewritten to match, then verified against those metrics. Real WeChat messages have a median of 8–18 characters with 40–70% short sentences; raw LLM output is 40–70 characters with almost none. That gap matters more than word choice.

Layout: `SKILL.md` (entry) · `references/` (judge / compose / style / routes + 43-doc knowledge base) · `scripts/style_tool.py` (profile / check / feedback).

Requires no backend, no API key of its own, no fine-tuning. The knowledge base is reused from [goutoujunshi](https://github.com/shengjidaguai-china/goutoujunshi) under MIT; attribution in [NOTICE.md](NOTICE.md).

MIT licensed.
