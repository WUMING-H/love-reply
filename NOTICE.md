# 来源与版权归属

本仓库包含两类内容：本项目原创的代码与文档，以及按 MIT 许可收录的第三方知识与参考的设计结构。以下逐项说明，便于二次分发时保留正确声明。

## references/kb/ — 第三方知识库

- **来源**：https://github.com/shengjidaguai-china/goutoujunshi
- **版权**：Copyright (c) 2026 powerycy
- **许可**：MIT License（完整条款见 `licenses/goutoujunshi-LICENSE`）
- **范围**：`references/kb/knowledge/`（20 篇）与 `references/kb/practical/`（23 篇），共 43 篇 Markdown
- **修改情况**：**未修改原文**。仅调整了存放路径（保留 `knowledge/` `practical/` 两级目录结构，以维持文档间的相对链接）。
- **本项目新增**：检索路由表 `references/routes.md`、各篇的调用时机说明（见 `documentation/knowledge-base.md`）均为原创，不属于上游内容。

该知识库在流程中承担检索依据的角色：生成候选前按需读取 2–3 篇作为策略参考，不参与模型训练，原文不进入输出文本。

## 判断协议的结构参考

`references/judge.md` 的七问组织方式（literal / intent / danger / give_substance /
best_action / need / resolved）与动作枚举的分类结构，参考了
[jev-chat/jev-chat-jarvis](https://github.com/jev-chat/jev-chat-jarvis)（MIT License）
的固定问题集设计。

- **参考范围**：问题的分类框架与枚举取值的组织方式
- **未复制代码**：本源文件为中文语境重写，判据、示例、边界情形、误判样例均为重新编写
- **本项目新增**：`stage`（关系阶段）维度、中文潜台词判据表、七类动作的允许条件、三个典型误判样例

## 本项目原创部分

以下内容由 WUMING-H 编写，以仓库根目录的 [LICENSE](LICENSE)（MIT）授权：

- `SKILL.md` 与七步流程的编排
- `references/` 中除 `kb/` 外的全部文件（judge / compose / style-guide / routes）
- `scripts/style_tool.py`（风格统计、校验、回流）与 `scripts/validate_skill.py`（完整性自检）
- `documentation/` 全部文档、`README.md` / `README_EN.md` / `CHANGELOG.md` 等
- 风格卡 schema、度量指标定义、按策略分档的校验阈值

## 使用与再分发

若你二次分发本仓库，请同时保留：

1. `LICENSE`（本项目 MIT 许可）
2. `licenses/goutoujunshi-LICENSE`（第三方知识库 MIT 许可原文）
3. 本 `NOTICE.md`

修改 `references/kb/` 下的原文时，请在该文件头部注明修改内容与日期，并说明原始来源——MIT 允许修改，但要求保留版权声明。
