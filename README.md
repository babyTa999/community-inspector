# IceWhale CRM

IceWhale 社区信号与用户 CRM 系统 - 用于管理社区反馈、问题和信号的完整 CRUD 应用，支持多人实时协作。

## 功能特性

- **完整的 CRUD 操作**：创建、读取、更新、删除条目
- **多人实时协作**：
  - WebSocket 实时同步
  - 乐观锁防止冲突
  - 编辑历史追踪
  - 在线用户显示
- **标签体系**：
  - 类型标签：R (Request)、Q (Question)、S (Signal)、Tips
  - 状态标签：已定位/知晓、待/判断/中、待修复、修复中、已解决等
- **多维度筛选**：关键词搜索、类型、状态、功能模块、相关人员、日期范围
- **仪表盘统计**：实时查看条目分布和趋势
- **Web 界面**：简洁美观的响应式 UI
- **REST API**：完整的 API 接口支持
- **CSV 导入**：支持从飞书多维表格导入数据

## 快速开始

### 1. 安装依赖

```bash
cd icewhale-crm
pip install -r requirements.txt
```

### 2. 配置数据库

**开发环境（SQLite，默认）**：
```bash
# 无需配置，直接使用 SQLite
```

**生产环境（PostgreSQL）**：
```bash
# 创建 .env 文件
cp .env.example .env

# 编辑 .env，配置 PostgreSQL
DATABASE_URL=postgresql://user:password@localhost:5432/crm
```

### 3. 初始化数据库

```bash
python crm_cli.py init
```

### 4. 启动服务

```bash
python crm_cli.py serve
# 或
python crm_cli.py serve --port 8080 --reload
```

### 5. 访问系统

打开浏览器访问 http://localhost:8080

## 多人协作功能

### 实时协作

- 打开条目详情页会自动连接 WebSocket
- 可以看到当前正在编辑该条目的其他用户
- 当其他人更新条目时，会收到实时通知

### 乐观锁

- 每个条目都有版本号
- 保存时会检查版本号，如果已被修改会提示冲突
- 冲突时可选择刷新查看最新内容

### 编辑历史

```bash
# 获取条目的编辑历史
GET /api/entries/{id}/history
```

## 项目结构

```
icewhale-crm/
├── crm/
│   ├── __init__.py
│   ├── models.py          # SQLAlchemy 数据模型（含协作字段）
│   ├── schemas.py         # Pydantic 模式
│   ├── database.py        # 数据库配置（SQLite/PostgreSQL）
│   ├── crud.py            # CRUD 操作（含乐观锁）
│   ├── search.py          # 搜索和筛选
│   ├── web.py             # FastAPI 应用（含 WebSocket）
│   ├── websocket.py       # WebSocket 处理
│   ├── templates/         # Jinja2 模板
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── list.html
│   │   ├── detail.html    # 含实时协作面板
│   │   └── form.html      # 含版本检查
│   └── static/            # 静态文件
├── crm_cli.py             # CLI 入口
├── import_csv.py          # CSV 导入工具
├── requirements.txt       # 依赖
├── .env.example           # 环境变量示例
└── README.md
```

## API 端点

### 条目管理

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/` | 仪表盘页面 |
| GET | `/entries` | 条目列表（支持筛选） |
| GET | `/entries/new` | 新建条目表单 |
| POST | `/entries` | 创建条目 |
| GET | `/entries/{id}` | 条目详情 |
| GET | `/entries/{id}/edit` | 编辑表单 |
| POST | `/entries/{id}` | 更新条目（支持乐观锁） |
| POST | `/entries/{id}/delete` | 删除条目 |

### API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/entries` | 列表条目 |
| GET | `/api/entries/{id}` | 获取条目 |
| GET | `/api/entries/{id}/version` | 获取版本号 |
| GET | `/api/entries/{id}/history` | 获取编辑历史 |
| POST | `/api/entries/{id}/edit-session/start` | 开始编辑会话 |
| POST | `/api/entries/{id}/edit-session/end` | 结束编辑会话 |
| GET | `/api/stats` | 获取统计 |

### WebSocket

| 路径 | 描述 |
|------|------|
| `/ws/entries/{id}?username={}&session_id={}` | 实时协作 WebSocket |

WebSocket 消息类型：
- `edit_start` - 开始编辑
- `edit_end` - 结束编辑
- `entry_update` - 条目更新通知
- `cursor` - 光标位置（未来扩展）
- `presence` - 用户上下线
- `heartbeat` - 心跳保活

## 数据模型

### 类型标签 (Type)

- **R** - Request: 功能请求/改进建议
- **Q** - Question: Bug/操作疑惑
- **S** - Signal: 趋势/风险/机会
- **Tips** - 技巧/教程

### 状态标签 (Status)

- `已定位/知晓` - 已定位/知晓
- `待/判断/中` - 待/判断/中
- `待修复` - 待修复
- `修复中` - 修复中
- `已解决` - 已解决
- `已回复` - 已回复
- `待回复` - 待回复
- `重要` - 重要

### 功能模块 (Feature Module)

- Files, App Store, Docker, 虚拟机, RAID, 备份
- 网络, 存储, UI/UX, 系统, 安全, 搜索
- Samba/SMB, 云盘, GPU, UPS, 监控/小组件
- 权限/账户, 文件加密, 迁移, 驱动
- 移动端, 桌面端, 体验优化, 第三方集成

## CSV 导入

支持从飞书多维表格导出的 CSV 导入：

```bash
python import_csv.py feishu_crm.csv
```

CSV 格式要求：
- 问题/需求描述,附件,链接,相关人员,tag,描述性tag,分析和todo,社区todo,名字,声量,更新记录日期,备注,父记录

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | 数据库连接字符串 | sqlite:///crm.db |
| `POSTGRES_HOST` | PostgreSQL 主机 | - |
| `POSTGRES_PORT` | PostgreSQL 端口 | 5432 |
| `POSTGRES_USER` | PostgreSQL 用户 | crm |
| `POSTGRES_PASSWORD` | PostgreSQL 密码 | - |
| `POSTGRES_DB` | PostgreSQL 数据库 | crm |
| `DEBUG` | 调试模式 | false |
| `HOST` | 服务器绑定地址 | 0.0.0.0 |
| `PORT` | 服务器端口 | 8080 |

## 技术栈

- **FastAPI** - Web 框架
- **SQLAlchemy** - ORM
- **SQLite/PostgreSQL** - 数据库
- **WebSocket** - 实时通信
- **Jinja2** - 模板引擎
- **Pydantic** - 数据验证

## License

MIT
