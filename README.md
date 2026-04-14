# forum-inspector

论坛巡检机器人：拉取近 24 小时论坛主题，分类后将中文 digest 输出到 Discord 频道。

## 功能
- 扫描论坛 `latest.json` 中近 24 小时内有活动的主题
- 使用 Claude 对主题进行分类：`Problem` / `Signal` / `UGC` / `Ignore`
- 输出中文摘要到指定 Discord 频道
- 记录已发送主题，避免重复播报

## 启动
复制 `.env.example` 为 `.env`，并填写：
- `DISCORD_BOT_TOKEN`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `MODEL_NAME`
- `GUILD_ID`
- `OUTPUT_CHANNEL_ID`
- `FORUM_BASE_URL`

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
docker compose logs -f forum-inspector
```

确认通过后，把 `.env` 中的 `DRY_RUN` 改回 `false`、`RUN_ON_STARTUP` 改回 `false`，再重新执行：

```bash
docker compose up -d --build
```

## 配置项
- `DIGEST_TIMEZONE`: digest 时间和调度使用的时区，默认 `Asia/Shanghai`
- `DIGEST_SCHEDULE_HOURS`: 每日执行小时，逗号分隔，默认 `10,12,14,16,18,20`
- `DRY_RUN`: `true` 时只采集和分类，不发消息、不写去重库
- `RUN_ON_STARTUP`: `true` 时 bot 启动后立即执行一次巡检
- `FORUM_ENABLED`: `true` 时启用论坛巡检
- `FORUM_BASE_URL`: 论坛基础地址

## 当前行为
- 扫描近 24 小时内有活动且未发送过的论坛主题
- 读取主题标题、摘要、主题链接和后续回复
- Problem 类型会显示“是否有人回复 / 是否已解决 / 知识库状态”
- 正常模式下发送成功后写入 `data/sent_messages.db` 去重；dry-run 不写入
