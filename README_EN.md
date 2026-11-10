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
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue.svg" alt="Python 3.9+">
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

Requires Python 3.9+ standard library only. The style tool installs nothing and makes no network calls.

## Usage

Three phrasings cover everything:

- **帮我回这条** + paste a conversation → judgment, three candidates, one warning.
- **他这句什么意思** + paste → judgment only, no drafts.
- **我想这么回，帮我改得像人话** + your draft → skip analysis, polish only.

Output is deliberately short: under 120 characters of commentary, judgment on the first line, three unquoted numbered options, then which one to send and what not to do. No JSON, no tables, no psychology jargon — those live inside the engine, not in front of someone reading on the subway.

## Style card

Without a card you get "how a normal person would reply". With one you get "how you would reply".

```bash
python scripts/style_tool.py profile --file my_messages.txt --slot couple_early
python scripts/style_tool.py check --text "下周六开幕" --strategy minimal
python scripts/style_tool.py feedback --slot couple_early --kind edited \
  --ai "周六下午我去接你" --user "周六 我过去"
```

`profile` computes length distribution, terminal-period rate, emoji density, short-sentence ratio and particle density, then **derives a forbidden list from what you never do**: no emoji in your corpus becomes "no emoji". Negative constraints are executable; "be witty" is not. The `avoid` list does the real work, not the sentence summarising your style.

Slots exist (`couple_early`, `couple_stable`, `friend`, `work`) to prevent bleed — affectionate phrasing aimed at a partner will misfire on a colleague.

The most valuable feedback is not "option 2" but "not me, I'd say XX". Your rewrite enters the sample pool and becomes the reference next time.

## Structure

```text
love-reply/
├── SKILL.md                 # entry: six steps, output contract, hard rules
├── references/
│   ├── judge.md             # 7 questions, Chinese subtext traps, misreads
│   ├── compose.md           # candidate strategies, danger tiers
│   ├── style-guide.md       # style card schema, cold start, few-shot
│   ├── routes.md            # intent × stage → which 2–3 docs
│   └── kb/                  # 43 Chinese documents (knowledge 20 / practical 23)
├── scripts/
│   ├── style_tool.py        # profile / check / feedback / show
│   └── validate_skill.py    # integrity and context-budget check
├── documentation/           # architecture, flows, knowledge base, style, safety
└── data/                    # your cards and feedback, git-ignored
```

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

## Credits and licensing

| Part | Attribution | Notes |
| --- | --- | --- |
| Judgment protocol structure | [jev-chat/jev-chat-jarvis](https://github.com/jev-chat/jev-chat-jarvis) (MIT) | Fixed-question and action-enum organisation referenced; criteria, examples and edge cases rewritten for Chinese; no code copied |
| 43-document knowledge base | [shengjidaguai-china/goutoujunshi](https://github.com/shengjidaguai-china/goutoujunshi) (MIT, Copyright (c) 2026 powerycy) | Included verbatim, unmodified; directory structure preserved to keep relative links working |
| Style layer, verifier, router, orchestration, docs | This project | Original |

MIT licensed. Keep `LICENSE`, `licenses/goutoujunshi-LICENSE` and `NOTICE.md` on redistribution. This project provides communication assistance and relationship education; it does not replace therapy, medical advice, legal counsel, or emergency services.
