# NOTICE · 第三方内容归属

本仓库不是全部原创。`references/kb/` 下的知识库来自另一个开源项目。

## references/kb/

- **来源**：https://github.com/shengjidaguai-china/goutoujunshi
- **版权**：Copyright (c) 2026 powerycy
- **许可**：MIT License（完整条款见 `licenses/goutoujunshi-LICENSE`）
- **范围**：`references/kb/knowledge/`（20 篇）与 `references/kb/practical/`（23 篇），共 43 篇 Markdown
- **修改情况**：**未修改原文**。仅调整了存放路径（保留 `knowledge/` `practical/` 两级目录结构，以维持文档间的相对链接），并在本仓库中新增了检索路由表 `references/routes.md`。

引用方式说明：本项目的判断层、生成层、风格层、校验层由 WUMING-H 编写；
知识库原样复用，用于在生成建议前做 2–3 篇的按需检索，不参与模型训练。

## 判断协议的来源

`references/judge.md` 里的七问结构（literal / intent / danger / give_substance /
best_action / need / resolved）与七类动作枚举，**借鉴自**
[jev-chat/jev-chat-jarvis](https://github.com/jev-chat/jev-chat-jarvis)（MIT License）
的固定问题集设计。

- **借鉴范围**：问题的分类框架与枚举取值
- **未复制代码**：本源文件为中文语境重写，判据、示例、边界情形均为重新编写
- **新增**：`stage`（关系阶段）维度、中文潜台词判据表、三个典型误判样例

仅作设计思路的出处标注。

## 其余部分

`SKILL.md`、`references/`（除 `kb/`）、`scripts/` 由 WUMING-H 编写，
以仓库根目录的 [LICENSE](LICENSE)（MIT）授权。

## 使用与再分发

若你二次分发本仓库，请同时保留 `LICENSE` 与 `licenses/goutoujunshi-LICENSE`，
以及本 NOTICE 文件。
