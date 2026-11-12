<p align="center">
  <a href="./README.md">简体中文</a> · <strong>English</strong>
</p>

<h1 align="center">Love Reply</h1>

<p align="center">
  <strong>Read the situation first. Then say it in your own voice.</strong>
</p>

<p align="center">
  Paste a Chinese chat log, get three replies you can send as-is,<br>
  plus one line on what the other person is actually asking, and one on what not to do.
</p>

<p align="center">
  <a href="https://github.com/WUMING-H/love-reply/stargazers"><img src="https://img.shields.io/github/stars/WUMING-H/love-reply?style=social" alt="GitHub Stars"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python 3.10+">
</p>

The moment you freeze in a chat window is rarely about not knowing what to say. It is about not knowing **what that message meant**. "哦" could be *got it*, or *I'm upset*. "下周" could be asking for a date, or checking whether you remembered. Guess wrong and no amount of polish saves you.

Most "AI reply" tools skip this and generate something warm, polite, and emotionally intelligent. It is always correct and never sounds like you. You would type `下周六开幕 我订两张`; they hand you `我很重视这次约定，已经提前安排好了时间，希望你能玩得开心`. What separates those two sentences is not craft — it is **identity**.

This project does two things. First it settles the situation with a fixed set of questions. Then it writes the conclusion back into **your own texting style**. Judgment decides *what to say*; the style layer decides *whether it sounds like you said it*. Get the first wrong and everything downstream is wasted. Get the second wrong and it reads as fake instantly.

It is a Skill, not an app: no backend, no database, no API key of its own, and no access to your messaging apps. You paste the few lines you want to answer.

## What it is good for

| Situation | What you get |
| --- | --- |
| You have rewritten one message three times and still not sent it | Three sendable candidates with genuinely different tone and length |
| You cannot tell whether they are upset | One sentence on what that message is asking — literal, or subtext |
| You want to apologise without making it worse | The right granularity: apologise for the specific thing, not your character |
| You want to move things forward | A concrete invitation with a time you can actually keep |
| You are always the one carrying the conversation | A read on whether the investment is mutual, and how to step back gracefully |
| You keep thinking "why did I say it like that again" | A style card that makes your phrasing the default |
| You suspect manipulation, or are tempted by it | Recognition and alternatives — not techniques |
| Stalking, threats, self-harm, violence | Immediate stop: helplines only |

## Two design decisions that matter

**1. Judge before you write.** Seven questions are answered in a single pass: is the last message purely literal; what is the real intent; how dangerous is this (0–9); does it need substance; what is the best action; what does the other person need; is the tension resolved. Generating without judging is guessing, and Chinese chat has an extremely high subtext density.

One dimension is usually missed: **relationship stage**. The same "想你了" is a signal of interest while dating, a request while partnered, and an olive branch during a cold war. Without a stage baseline a model can only produce an average answer, and an average answer is wrong for every specific relationship.

**2. Sound like you, not like "a decent person".** This is the real difference, and the most misunderstood one. The goal is not *human-sounding*, it is *you-sounding*. "Human-sounding" cannot be verified — any fluent, warm message already is. "You-sounding" can be: mix five of your messages with five of its, ask someone who knows you to pick out yours, and only near-chance accuracy counts as passing.

The gap is not vocabulary, it is **length**. Real WeChat messages have a median of 8–18 characters with 40–70% short sentences; raw LLM output runs 40–70 characters with almost no short ones, and adds a full stop at the end. That is far more visible than word choice. So the first move of the style layer is never synonym swapping — it is cutting the sentence apart, dropping the full stop, deleting the preamble.

Measurement is done in plain code, not by the model. A model cannot count that your terminal-period rate is 0.06; ask it to estimate and it will guess 0.3, and the distance between 0.06 and 0.3 is exactly the distance between "like you" and "not".

```
chat log
 ├─ 1 normalize   split speakers, drop nicknames, facts / inferences / unknowns
 ├─ 2 judge       7 fixed questions + relationship stage, one call
 ├─ 3 retrieve    2–3 docs by intent × stage, never the whole library
 ├─ 4 compose     lock the goal, then 3 candidates with distinct strategies
 ├─ 5 style       rewrite into your phrasing, per persona slot
 └─ 6 verify      hard rules + style metrics, two gates
      └→ 3 candidates + 1 line of judgment + 1 "don't do this"
```

## A Chinese relationship knowledge base you can actually call

43 Chinese documents covering attraction, ambiguity, conflict, marriage, law, and crisis referral. It is not a phrasebook — it carries an evidence tier for each claim, separating research findings from popular advice from field heuristics.

| Area | Contents |
| --- | --- |
| Relationship psychology | Attraction, responsiveness, social exchange, commitment, power, repair |
| Emotion and personality | Attachment, anxiety and avoidance, regulation, MBTI limits |
| Dating | Initiation, first meetings, invitations, defining the relationship, digital boundaries |
| Communication | Turn-taking, empathy, praise, refusal, apology, conflict, rehearsal |
| Manipulation | PUA and classic social systems: mechanisms, evidence, ethical alternatives |
| Consent | Ongoing consent, sexual communication, bodily autonomy, negotiation |
| Marriage and family | Premarital agreements, finances, chores, in-laws, family lifecycle |
| Law and safety | Chinese family law, domestic violence, stalking, fraud, crisis referral |
| Breakup and repair | Loss, betrayal, reconciliation, rebuilding trust, disengaging |
| Evidence and limits | Evidence tiers, content boundaries, when not to advise |

Only 2–3 documents are loaded per request. More is not more accurate — it turns the output into a literature review instead of a line you can send. Knowledge influences strategy only and never appears in the text: the acceptance test is that deleting everything you read leaves the candidates byte-identical.

## Install

Send this to your AI assistant:

```text
Download and install the public repository https://github.com/WUMING-H/love-reply as a local Skill.
```

Or place it manually:

```bash
git clone https://github.com/WUMING-H/love-reply.git
cp -r love-reply ~/.claude/skills/love-reply     # or ~/.workbuddy/skills/
```

Requires Python 3.10+ standard library only (CI covers 3.10 / 3.12 / 3.13). The style tool installs nothing and makes no network calls.

## Usage

Three phrasings cover everything:

- **帮我回这条** + paste a conversation → judgment, three candidates, one warning.
- **他这句什么意思** + paste → judgment only, no drafts.
- **我想这么回，帮我改得像人话** + your draft → skip analysis, polish only.

Output is deliberately short: under 120 characters of commentary, judgment on the first line, three unquoted numbered options, then which one to send and what not to do. No JSON, no tables, no psychology jargon — those live inside the engine, not in front of someone reading on the subway.

## Style card

Without a card you get "how a normal person would reply". With one you get "how you would reply".

```bash
# no corpus needed: pull your own lines out of the conversation you just pasted
python scripts/style_tool.py sample --file my_lines.txt --slot couple_early

python scripts/style_tool.py profile --file my_messages.txt --slot couple_early
python scripts/style_tool.py check --text "下周六开幕" --strategy minimal

# record what you actually picked, and how you rewrote it
python scripts/style_tool.py feedback --slot couple_early --kind chosen \
  --strategy minimal --ai "周六 我过去"
python scripts/style_tool.py feedback --slot couple_early --kind edited \
  --strategy minimal --ai "周六下午我去接你" --user "周六 我过去"
```

`profile` computes length distribution, terminal-period rate, emoji density, short-sentence ratio and particle density, then **derives a forbidden list from what you never do**: no emoji in your corpus becomes "no emoji". Negative constraints are executable; "be witty" is not. The `avoid` list does the real work, not the sentence summarising your style.

Slots exist (`couple_early`, `couple_stable`, `friend`, `work`) to prevent bleed — affectionate phrasing aimed at a partner will misfire on a colleague.

**You rarely have a corpus, and that is the normal case.** The lines you already sent are sitting in the conversation you just pasted — your own bubbles are on the right. `sample` measures those and produces a card for this one reply.

Below twelve messages it gives you only the forbidden list, never a length ceiling: in a single conversation you may be writing short *because she is angry*, and the median of six messages is that evening's state, not your habit. Such cards are marked `small_sample` and `check` falls back to absolute ceilings — the `avoid` entries still apply, because "you never do X" does not depend on a distribution.

Sampled cards are not written to disk by default. `--save` stores one, and it will not overwrite a corpus card unless you pass `--force`.

The most valuable feedback is not "option 2" but "not me, I'd say XX". Your rewrite enters the sample pool and becomes the reference next time.

**Feedback used to be a dead end** — the log was written and never read, which is worse than not having it, because it makes you believe the thing is getting more accurate. It is now wired in: after five votes `verify` adds a `habit` line naming the strategy you reach for, and an edit rate above 40% suggests the style card has drifted.

With one hard limit: **preference only ranks, it never admits.** No number of votes will let a stage-forbidden strategy through, otherwise you get "you like this tone, so here is an invitation during the repair period". That is precisely what the stage gate exists to prevent.

## Relationship profile

The style card handles *sounding like you*. The profile handles *being right about her*.

Seven kinds of entries, stored locally as plain JSON: `fact` (verifiable), `read` (your interpretation, with confidence), `unknown` (explicitly not known), `landmine`, `soother`, `promise` (with a due date), `event`.

```bash
python scripts/profile_tool.py init --slot couple_early --alias 她 --stage couple_early
python scripts/profile_tool.py add --slot couple_early --kind landmine \
  --text "她说累的时候别讲道理"
python scripts/profile_tool.py brief --slot couple_early --query "她说今天好累"
```

**Facts and reads are kept apart on purpose.** Once an inference is written down as a fact it stops being questioned — six months later you are still acting on a conclusion that came from one misunderstanding. So reads carry a confidence level: `high` can drive decisions, `mid` only tunes tone, `low` may only produce a probing reply ("ask her, don't decide for her"). Low-confidence entries come out with a `?` marker.

Two entries change output the most: **landmines** (so it never hands you a lecture when she is exhausted) and **open promises** (so it never suggests you offer something you already owe).

The profile is also forbidden from touching `danger`. Danger is read from the current exchange only — a tense month does not make "what's for dinner" a 5.

Reads expire. `stale` lists what has not been confirmed in 60 days; `accept` refreshes one, `forget` drops it. A profile left untouched describes a person who no longer exists, and acting on it is worse than having none.

**Tag facts when you record them, or they will never come back.** This was measured: "she doesn't eat mango" was stored, then "I want to buy her some fruit" retrieved nothing — because two Chinese sentences phrased differently share no characters, and no similarity weighting fixes zero overlap either.

```bash
python scripts/profile_tool.py add --slot couple_early --kind fact \
  --text "她不吃芒果" --tag 芒果 水果 过敏 --core
```

`--tag` takes category words and is matched alongside the text. `--core` marks the entries that must be obeyed rather than recalled — allergies, dislikes, birthdays — and those skip retrieval and ride along every time. **Retrieval is a probability, compliance is an obligation**; the two do not belong in the same mechanism.

No vector search, deliberately: tags are written by the person who knows, so they are inspectable and fixable. An embedding model that retrieves the wrong thing gives you neither.

## Stage is a gate, not a parameter

The same intent — *let's meet this weekend* — has six different correct forms depending on where the relationship stands:

| Stage | What you can say | Why |
| --- | --- | --- |
| just added | You saw that exhibition too? I went last week. | You cannot ask yet; asking is a demand |
| talking, not met | There's a show this weekend, if you're free | You can ask, but leave an exit |
| met 1–3 times | Saturday 2pm, I'll book two | Give a time; she only has to answer yes or no |
| together < 6 months | Saturday 2pm, then that place you mentioned | No need to ask; assume together, add her detail |
| stable | Which session do you want to see on Saturday? | It's a shared calendar; ask preference, not willingness |
| repairing | (say nothing about it) | Any invitation reads as "let's bury this" |

So stage is enforced as a whitelist, not a weight. `stranger` does not *score lower* for `advance` — `advance` is not allowed to exist. Scoring produces "slightly off"; gating produces "not shown", and timing errors need the latter.

Three counter-intuitive rules: no `hold` when you just met (leaving space requires existing presence), no `hold` while dating (silence reads as disinterest), and **lowest detail density during repair** — "I left at six, traffic was forty minutes, I really didn't mean it" is heard as "he's building a case".

There is also one mechanically checked rule: in the talking stage an invitation must contain an exit ("if you're free", "no pressure", "only if you want"). Without one it fails the gate.

## Self profile and goals

Knowing her is half of it. The other half is knowing what you want, which the default model never optimises for — it optimises how well the message lands, and the message that lands best is usually the reconciliatory one, even when you want out.

Six kinds of self entries: `trait`, `flaw`, `limit`, `capacity`, `value`, `voice`. `limit` and `flaw` must carry literal trigger words, because the gate matches text, not meaning:

```bash
python scripts/profile_tool.py self add --kind limit   --text "不会为了恋爱换城市" --forbid 搬过去 去你那边
```

Goals have five directions — `advance`, `hold`, `repair`, `exit`, `understand` — and three horizons. Hard goals **filter**, soft goals **rank**. `exit` is the one place the stage gate relaxes: you are not maintaining the relationship, only finishing the sentence.

When goal and stage conflict, stage wins. The correct output is not to abandon the goal but to say so: "this lands wrong today; first settle the thing from last week."

## How you know it hasn't broken

Change one instruction, loosen one gate: the effect is immediate, the damage is delayed. By the time "replies feel off lately" reaches you, three versions have shipped and you no longer know which one to roll back to.

So there is a fixed suite: `evals/cases.jsonl`, twenty-four scenes covering all six stages and all six strategies. Each scene declares three candidates that **must pass** and one or two that **must be blocked**, checked by `scripts/eval_skill.py` with mechanical assertions only.

```bash
python scripts/eval_skill.py        # offline, no model calls, no style card needed
```

```text
24 cases
  good candidates 72 · passed 72 · wrongly blocked 0
  bad candidates  29 · blocked 29 · let through 0
  coverage: stages 6/6 · strategies 6/6
result: all passed
```

**It tests the floor, not the ceiling.** Whether a stage-forbidden strategy was blocked, whether an overlong line was cut, whether jargon leaked into a candidate, whether hard goals and self-limits fired — all mechanically checkable. It cannot tell you whether a line was *good*; that needs a human or a blind test. Accepting that boundary is more useful than building an evaluator that gives itself high marks.

**It caught a real bug on day one.** Three cases went red, and one was not a bad test: the two-character reply 「没有」 was rejected as "too short, may have lost information". In Chinese chat 「没有」「不去」「好啊」 are the most common answers, and forcing them longer is distortion, not improvement.

Adding a scene needs no code — append a line:

```json
{"id":"c5","stage":"couple_early","paste":"她：算了 不说了","traps":"withdrawing is not resolving",
 "good":[{"strategy":"minimal","text":"…"},{"strategy":"care","text":"…"},{"strategy":"repair","text":"…"}],
 "bad":[{"strategy":"advance","text":"…","gate":"content","why":"no advancing during repair"}]}
```

`gate` is `content`, `style`, `term` or `either`. The cases are checked too: fewer than three passing candidates, overlapping strategies, or a misspelled stage name fails the run.

## Structure

```text
love-reply/
├── SKILL.md                 # entry: judge → write → gate, output contract, hard rules
├── AGENTS.md                # derived from SKILL.md, for AGENTS.md hosts (Codex, Cursor)
├── references/
│   ├── judge.md             # 7 questions, Chinese subtext traps, misreads
│   ├── compose.md           # candidate strategies, danger tiers, promises
│   ├── style-guide.md       # style card schema, cold start, few-shot
│   ├── profile.md           # her: 7 entries, confidence, injection, bias guards
│   ├── self.md              # you: 6 entries, goal arbitration, self-bias traps
│   ├── stages.md            # 6-stage matrix, evidence, migration signals
│   ├── routes.md            # intent × stage → which 2–3 docs
│   └── kb/                  # 43 Chinese documents (knowledge 20 / practical 23)
├── prompts/
│   ├── standalone.md        # self-contained prompt for any chat model
│   ├── profile-interview.md # twelve questions: her profile
│   └── self-interview.md    # twelve questions: your profile and goals
├── scripts/
│   ├── style_tool.py        # profile / sample / check / feedback / show
│   ├── profile_tool.py      # her / you / goals / stage card / guard / verify / prefs
│   ├── eval_skill.py        # floor tests over fixed scenes
│   └── validate_skill.py    # integrity: files, required sections, entry-point agreement
├── evals/
│   └── cases.jsonl          # 24 scenes: candidates that must pass, candidates that must fail
├── documentation/           # architecture, flows, knowledge base, style, stages, self, evaluation, safety
└── data/                    # style/, profile/ (+goals), self.json, feedback (git-ignored)
```

## Using it in any model

| Host | Entry point |
| --- | --- |
| WorkBuddy, Claude Code | `SKILL.md` |
| Codex, Cursor | `AGENTS.md` |
| Any web chat model | paste `prompts/standalone.md` |

The standalone prompt is self-contained — judgement, candidates, style rules, profile section, output format. It loses the knowledge base, the measured style card and the structured profile, but the output contract is identical. See [documentation/portability.md](documentation/portability.md).

## Principles

1. **Judge, then express.** A well-written wrong read is just a more persuasive mistake.
2. **Sound like you, not like a decent person.** Generic politeness is a failure mode.
3. **Knowledge informs strategy, never text.** Jargon makes the user translate for us.
4. **Code measures, the model interprets.** Numbers from statistics, meaning from the model.
5. **Only promise what can be delivered.** Times and plans must be keepable.
6. **Safety outranks rapport.** Stalking, threats, self-harm and violence get helplines, not phrasing.

## What it refuses

- Scoring whether someone loves you — behaviour and patterns are readable, feelings are not.
- Screen-scraping chat apps; pasting takes five seconds and carries no ban risk.
- Sending messages on your behalf.
- Manipulation: manufactured anxiety, silent treatment as pressure, fake personas, "testing" people.
- Fine-tuning a small model; a style card is one JSON edit away.

## Maintenance

Full release notes in [CHANGELOG.md](CHANGELOG.md). Current version: **0.9.0**.

Contributions welcome — knowledge, criteria, test scenes, failure reports. Read [CONTRIBUTING.md](CONTRIBUTING.md) first. The most valuable contribution is an anonymised real scene, especially one where the judgment was wrong.

## Credits and licensing

| Part | Attribution | Notes |
| --- | --- | --- |
| Judgment protocol structure | [jev-chat/jev-chat-jarvis](https://github.com/jev-chat/jev-chat-jarvis) (MIT) | Fixed-question and action-enum organisation referenced; criteria, examples and edge cases rewritten for Chinese; no code copied |
| 43-document knowledge base | [shengjidaguai-china/goutoujunshi](https://github.com/shengjidaguai-china/goutoujunshi) (MIT, Copyright (c) 2026 powerycy) | Included verbatim, unmodified; directory structure preserved to keep relative links working |
| Style layer, verifier, router, orchestration, docs | This project | Original |

MIT licensed. Keep `LICENSE`, `licenses/goutoujunshi-LICENSE` and `NOTICE.md` on redistribution. This project provides communication assistance and relationship education; it does not replace therapy, medical advice, legal counsel, or emergency services.
