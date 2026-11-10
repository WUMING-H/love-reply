# 跨宿主与跨模型

这个 Skill 不绑定任何一个厂商。同一套流程有三种入口，行为一致；差别只在能用多少能力。

---

## 一、三种入口

| | `SKILL.md` | `AGENTS.md` | `prompts/standalone.md` |
|---|---|---|---|
| 谁读 | Claude Code、WorkBuddy 等 | Codex、Cursor 等 | 任何聊天模型 |
| 知识库 | 43 篇按需检索 | 同左 | 无 |
| 风格卡 | 统计过的指标 | 同左 | 文字描述 |
| 恋爱档案 | 结构化，可检索 | 同左 | 手动粘贴一段 |
| 校验 | `style_tool.py` 双闸门 | 同左 | 模型自查 |
| 需要装环境 | 是 | 是 | 否 |

判断成不成立、候选像不像人，主要看提示词；准不准、像不像你，主要看知识库、档案和风格卡。
所以网页版临时用完全够，长期用才需要装。

---

## 二、安装位置

```text
WorkBuddy            ~/.workbuddy/skills/love-reply/
Claude Code          ~/.claude/skills/love-reply/
Codex                ~/.codex/ 或项目的 .agents/ 目录（读 AGENTS.md）
Cursor               项目根目录的 AGENTS.md（软链到本仓库的 AGENTS.md 即可）
其他                任何会扫描 SKILL.md 或 AGENTS.md 的宿主
```

Windows 上如果想把本体放别的盘，用目录联接指过去（`mklink /J`），读写都落到真实目录：

```bat
mklink /J "C:\Users\<你>\.workbuddy\skills\love-reply" "E:\skills\love-reply"
```

**不要在两个位置各放一份拷贝。** 风格卡和档案只写在 `data/`，两份拷贝会各写各的，很快就不一致了。

---

## 三、数据在哪、怎么共用

所有个人数据都在 `<skill>/data/`：

```
data/
├── style/{slot}.json       风格卡
├── profile/{slot}.json     对她的档案 + 关系目标（goals）
├── self.json               自我档案（全局一份，不随对象变）
└── feedback.jsonl          点选 / 改写记录
```

**一台机器上多个宿主共用**：只要它们指向同一个目录，就自动共享。这是放 `data/` 而不是放
`~/.love-reply` 的原因——宿主换了，数据不跟着搬。

**多台机器**：把 `data/` 放进一个私有 git 仓库，或者用网盘同步。注意 `data/` 里是你自己写的话
和对别人的观察，**不要放在公开仓库**，也不要放进公司网盘。

**换机器 / 备份**：

```bash
python scripts/profile_tool.py export --slot couple_early --out 档案.md
```

导出的是人能读的 Markdown，可以直接看，但**不能直接导回去**——需要重建时按导出内容重新 `add`。
自我档案单独导出：`python scripts/profile_tool.py self export --out 我.md`。

**清空**：删掉 `data/` 整个目录。风格卡和档案都会没，Skill 退回安全默认继续工作。

---

## 四、跑不了脚本时怎么降级

有些宿主只读文件、不执行命令。这时按下面的方式手工替代，**不要因为跑不了脚本就停下来问用户**。

| 脚本 | 手工替代 |
|---|---|
| `profile_tool.py brief` | 读 `data/self.json` 与 `data/profile/{slot}.json`，按 `references/profile.md` 第 4 节的优先级自己挑：硬目标 → 底线 → 阶段任务 → 相关条目 4–6 条 |
| `profile_tool.py stage` | 查 `references/stages.md` 的六阶段表，取该阶段允许/禁止的策略、细节密度、字数上限 |
| `profile_tool.py guard` | 目测三件：候选里有没有他自己写的底线词、策略是否在该阶段被禁、有没有接住档案里的具体事实 |
| `style_tool.py show` | 读 `data/style/{slot}.json` 的 `metrics` 和 `strategy.avoid` |
| `style_tool.py check` | 按 `references/style-guide.md` 的硬规则目测：字数是否超上限、有没有句号、有没有 emoji、有没有 AI 味短语 |

手工版比脚本版差，但差得不多——真正起作用的是"知道该看哪几个数"，不是那个脚本本身。

---

## 五、模型差异

同一个提示词在不同模型上表现不同，主要差在三处：

| 差异 | 表现 | 应对 |
|---|---|---|
| 指令跟随 | 弱一点的模型会把「不要输出分析」理解成「少输出分析」 | 输出格式那段放最前面，越具体越好 |
| 长度控制 | 模型普遍偏长，弱模型更严重 | 靠校验拦，或在提示词里写死字数上限 |
| 潜台词判断 | 强模型能读出「行吧」的降调，弱模型当同意 | 把 `judge.md` 的陷阱表整段带上，不要省略 |

经验：**判断层吃模型能力，风格层吃规则**。模型弱的时候，不要指望它自己判断得多准，
多给它具体规则和反例；模型强的时候，规则可以少给，让它自己权衡。

不建议为了某个模型单独改提示词。如果一定要改，改 `prompts/standalone.md` 的【风格】段，
那是唯一与模型能力弱相关、又不会破坏判断的部分。

---

## 六、跨宿主的一致性

三种入口共享同一套判断标准和输出格式，但**不保证输出一模一样**。差异来自：

- 有没有知识库（`references/kb/` 43 篇只在装了的宿主里生效）
- 有没有风格卡（统计值 vs 文字描述）
- 模型本身

所以换宿主之后，不要拿两次输出逐字对比。要对比就对比三件事：
**判断对不对、三条是不是真不同、长度像不像你。**

---

## 七、最小可用组合

如果只想记一件事：**装 `SKILL.md` 那一套，然后建风格卡。**

判断层带来的提升（不判错）是一次性的，风格卡带来的提升（像你）是每次都在的。
两个都没有时，它仍然能给你三条能发的话——只是那三条，换个人也发得出来。
