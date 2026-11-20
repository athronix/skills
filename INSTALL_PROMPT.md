# athronix Skills — 安装程序模板（INSTALL PROMPT）

> **用法**：对你的 AI agent 说一句 ——
> `请按照 https://raw.githubusercontent.com/athronix/skills/main/INSTALL_PROMPT.md 安装 <skill-name>`
> 其中 `<skill-name>` 替换为目标 skill（如 `skill-dev-git`）。
>
> 本文件人工维护、public 匿名可读；`marketplace.json` / `<skill>.link.json` 由聚合仓 CI 机器重建。
> 你是执行安装的 agent：把下文 `<skill-name>` 替换为用户指定的 skill 名，严格按步骤顺序执行。

## 1. 读指针（聚合仓 public，匿名访问）

`GET https://raw.githubusercontent.com/athronix/skills/main/<skill-name>.link.json`

取字段：`repo` / `clone` / `visibility` / `version` / `package`。
（`version` 不带 v 前缀；release tag 为 `v<version>`。）

- **raw 404 别急着下结论**：raw.githubusercontent.com 会缓存 404（负缓存），新发布/刚生成的文件常出现"假 404"。收到 404 先走实时 API 复核一次：
  `GET https://api.github.com/repos/athronix/skills/contents/<skill-name>.link.json`（带 `Accept: application/vnd.github.raw` 头，公开仓可匿名）→ 200 则直接采用其内容继续；仍 404 才认定文件不存在。
- 确认不存在 → 兜底：`GET https://api.github.com/repos/athronix/skills/contents/marketplace.json`（同上带 raw accept 头），在 `plugins[]` 找 `name==<skill-name>` 的条目（`source` 即 repo，`x-athronix.release.asset` 即 package）。
- 仍找不到 → 向用户报告「该 skill 未在 athronix 市场注册」并停止。**不要猜测近似名字的仓。**

## 2. 凭据（skill 仓默认 private）

若 `visibility == "private"`：需要 fine-grained PAT（权限 Contents: Read-only 即可）。

- 依次探测环境变量 `GITHUB_READ_TOKEN`、`GH_TOKEN`；有则用。
- 都没有 → **停下来向用户索要**（提示：https://github.com/settings/personal-access-tokens 生成，只勾 Contents read）。
- 绝不打印 token 值；绝不把 token 发往 github.com / api.github.com 之外的任何地址；匿名 404 后不要反复重试。
- `visibility == "public"` → 跳过本节，全程匿名。

## 3. 获取产物（优先 release zip，保证与发布快照一致）

**先把落盘目录定好，后面都用 `$STAGE`**（末尾两条命令都要用到它）：

```bash
STAGE="${TMPDIR:-$HOME/wbtmp}/athronix-skill"; mkdir -p "$STAGE" || STAGE="$PWD"
```

> **绝对不要用 `/tmp`**。鸿蒙（HarmonyOS）沙箱的 `/tmp` 是**只读** tmpfs：`touch /tmp/x`
> 报 `Read-only file system`，`curl -o /tmp/x` 报 `curl: (23) client returned ERROR on write`。
> 这条错误看起来像网络问题，极易误判成「下载失败/源不可达」而反复重试。
> 上面这行 `$STAGE` 的三级回退（`$TMPDIR` → `$HOME/wbtmp` → 当前目录）在所有平台都成立。

**方式 A（默认，release zip）**：

- `visibility == "public"`：匿名直链下载即可
  ```bash
  curl -fsSL "<package>" -o "$STAGE/<skill-name>-<version>.zip"
  ```
- `visibility == "private"`：**不要**直接 curl `package` 直链——私有 asset 的 `browser_download_url` 会 302 到签名域名并剥离 Authorization 头，带 token 也返回 404（实测）。正确姿势走 API：
  ```bash
  curl -fsSL -H "Authorization: Bearer $GITHUB_READ_TOKEN" \
    "https://api.github.com/repos/athronix/<skill-name>/releases/tags/v<version>" \
    | grep -o '"url": *"[^"]*assets/[^"]*"' | head -1 | sed 's/.*"url": *"//; s/"$//' \
    | xargs -I{} curl -fsSL -H "Authorization: Bearer $GITHUB_READ_TOKEN" \
        -H "Accept: application/octet-stream" "{}" -o "$STAGE/<skill-name>-<version>.zip"
  ```
  （取该 release 的 asset API url——不是 browser_download_url——带 token + `Accept: application/octet-stream` 下载；多个 asset 时取 `<skill-name>-<version>.zip` 那个。）

- 需要可编辑源码或上面失败 → **方式 B**：`git clone <clone>` 并 checkout tag `v<version>`。私有仓 clone 形式：`https://x-access-token:$GITHUB_READ_TOKEN@github.com/athronix/<skill-name>.git`（token 不落 remote 配置）。
- tag 不存在（如本地已 release 未同步市场）→ 退回 clone 默认分支 HEAD，并在最终报告标注「装的是 HEAD 非发布版」。

## 4. 装载到你的 agent 的 skills 目录

先解压到 `$STAGE`（同样**不要**用 `/tmp`）：

```bash
unzip -q -o "$STAGE/<skill-name>-<version>.zip" -d "$STAGE"
```

解压后目录顶层为 `<skill-name>/`，内含 `SKILL.md`（+ `scripts/` `references/` `assets/` 视 skill 而定）：

| Agent | 目标目录 |
|-------|----------|
| WorkBuddy | `~/.workbuddy/skills/<skill-name>/` |
| Claude Code / CodeBuddy | `~/.claude/skills/<skill-name>/` |
| 其它 | 该 agent 的 skills 装载目录（遵循根 SKILL.md 的 Agent Skills 通用格式） |

同名已存在 → 先整目录备份（目录名含旧版本号）再覆盖，保证可回滚；**禁止静默删除旧目录**。

> **备份前先判一次符号链接**。不少环境用 `~/.workbuddy/skills/<skill-name>` →
> 某个 git 仓库目录的软链来共享同一份 skill。此时：
> - `cp -r` / `cp -a` 备份的是**链接本身**，恢复后得到一条**指向旧路径的悬空链**；
> - 直接用 `cp -r` 覆盖会**写穿链接**、改到源仓库（更糟的是静默改）。
>
> 正确做法：`[ -L <目标> ]` 为真时，只**替换链接指向**（或先 `readlink` 记录原指向再删链重建），
> 不要对链接目标做递归复制。备份记录里写清「原为符号链接 → <readlink 结果>」。

## 5. 验证与报告（全部满足才算成功）

- `<skill-name>/SKILL.md` 存在，frontmatter `name == <skill-name>`；
- frontmatter `version == link.json 的 version`（走 clone-HEAD 回退时除外，需标注）；
- skill 声明的 `scripts/` `references/` 路径真实存在；
- 向用户报告：**skill 名、安装版本、安装路径、所用方式（A zip/B clone）、备份位置（若覆盖）**。

## 纪律

- token 不落盘、不回显、不写进任何脚本/配置/日志。
- 每一步失败如实报告原始错误（HTTP 码 + 响应 message 摘要），不伪造成功、不跳步。
- 本模板与 skill 内容冲突时，以 skill 自身 SKILL.md 的使用说明为准。
