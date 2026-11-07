# athronix skills — aggregate marketplace

每个 skill 独立 repo：`athronix/<skill>`（根目录 `.skill` 标记文件为判定凭据）。

- `marketplace.json` — 全量市场元数据（规范字段 + `x-athronix` 扩展），**机器生成，勿手工编辑**
- `<skill>.link.json` — 每个 skill 的 repo hyperlink，机器生成
- `scripts/scan_and_sync.py` — 扫描+重建逻辑（本地 `scan` 只读预览 / CI `sync` 落盘）
- `.github/workflows/sync-marketplace.yml` — 唯一写者：每日 cron + release dispatch + 手动；提交带 `[skip ci]` 防循环

## 任意 AI Agent 消费方式

skill 遵循通用 Agent Skills 格式（根 `SKILL.md` frontmatter name/description + scripts/references/assets）：

1. 读 `marketplace.json` 的 `plugins[]` 或 `<skill>.link.json` 拿到 repo 地址；
2. public skill：`git clone` 或下载 Release 的 zip asset，解压进你的 skills 目录；
3. private skill：clone/下载需 fine-grained PAT（Contents read）。

维护通道由 `athronix/skill-dev-git` skill 驱动（WorkBuddy 会话中说"发布 skill"即可）。
