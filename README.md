# discord-inspector
Discord 社区巡检机器人：拉取近 24 小时消息，分类后输出中文 digest。

## 启动
复制 `.env.example` 为 `.env`，并填写 `DISCORD_BOT_TOKEN`、`ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、`MODEL_NAME`、`GUILD_ID`、`OUTPUT_CHANNEL_ID`。

本机 Docker Desktop 部署：

如果你用 Git Bash：

```bash
cp .env.example .env
```

如果你用 PowerShell：

```powershell
Copy-Item .env.example .env
```

首次验证建议先在 `.env` 中设置：

```env
DRY_RUN=true
RUN_ON_STARTUP=true
FORUM_ENABLED=true
```

然后启动并查看日志：

```bash
docker compose up -d --build
docker compose logs -f discord-inspector
```

首次验证时，重点确认 bot 登录、数据库初始化成功，并立即触发一次 dry-run digest。

确认通过后，把 `.env` 中的 `DRY_RUN` 改回 `false`、`RUN_ON_STARTUP` 改回 `false`，再重新执行：

```bash
docker compose up -d --build
```

## 可选配置
- `INCLUDE_CHANNEL_IDS`: 仅扫描这些频道 ID，逗号分隔。
- `EXCLUDE_CHANNEL_IDS`: 排除这些频道 ID，逗号分隔；优先级高于 include。
- `DIGEST_TIMEZONE`: digest 时间和调度使用的时区，默认 `Asia/Shanghai`。
- `DIGEST_SCHEDULE_HOURS`: 每日执行小时，逗号分隔，默认 `10,12,14,16,18,20`。
- `DRY_RUN`: `true` 时只采集、分类、渲染，不发消息、不写去重库。
- `RUN_ON_STARTUP`: `true` 时 bot 启动后立即执行一次 digest。
- `FORUM_ENABLED`: `true` 时启用论坛巡检。
- `FORUM_BASE_URL`: 论坛基础地址，默认 `https://community.example.com`。

## 当前行为
- 扫描近 24 小时内未发送过的 Discord 消息。
- 默认扫描所有可读文本频道；配置 include/exclude 后按频道 ID 过滤。
- 可选额外扫描论坛 `latest.json` 中近 24 小时内**新创建**且未发送过的主题。
- 论坛巡检只按 topic `created_at` 判定是否为新主题；即使旧主题因为新回复被 bump 到顶部，也不会作为新问题再次播报。
- digest 会附带分类统计、消息时间和原始链接；论坛条目会额外显示主题标题。
- 正常模式下发送成功后写入 `data/sent_messages.db` 去重；dry-run 不写入。
