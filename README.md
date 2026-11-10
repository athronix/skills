# athronix skills — aggregate marketplace

每个 skill 独立 repo：`athronix/<skill>`（根目录 `.skill` 标记文件为判定凭据）。

- `marketplace.json` — 全量市场元数据（规范字段 + `x-athronix` 扩展），**机器生成，勿手工编辑**
- `<skill>.link.json` — 每个 skill 的 repo hyperlink，机器生成
- `scripts/scan_and_sync.py` — 扫描+重建逻辑（本地 `scan` 只读预览 / CI `sync` 落盘）
- `.github/workflows/sync-marketplace.yml` — 唯一写者：每日 cron + release dispatch + 手动；提交带 `[skip ci]` 防循环

## 任意 AI Agent 消费方式（一句话安装）

对你的 agent 说：

> 请按照 https://raw.githubusercontent.com/athronix/skills/main/INSTALL_PROMPT.md 安装 <skill-name>

`INSTALL_PROMPT.md`（人工维护）内置完整流程：读 `<skill>.link.json` 指针 → private 仓 PAT 纪律 → release zip 下载（API/clone 兜底）→ 装载到 WorkBuddy / Claude Code 等 skills 目录 → 版本一致性验证与报告。skill 遵循通用 Agent Skills 格式（根 `SKILL.md` frontmatter name/description + scripts/references/assets），任何 agent 均可用同一入口。

维护通道由 `athronix/skill-dev-git` skill 驱动（WorkBuddy 会话中说"发布 skill"即可）。
