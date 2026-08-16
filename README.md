# MVP AI部署助手

## 项目简介

MVP AI部署助手是一款在 Windows 本地运行的 AI 智能部署工具，支持**本地 Windows 部署**和**远程 Linux SSH 部署**两种模式。通过集成 DeepSeek AI 大模型，能够根据主机环境和项目配置自动生成最优部署计划，并提供实时日志推送、三重验证、自动回滚、监控告警等完整能力，大幅降低应用部署的复杂度和出错率。

前端采用 Vue 3 + Element Plus 构建可视化操作界面，后端基于 Python FastAPI 提供高性能 API 服务，数据持久化使用 SQLite（WAL 模式），远程操作通过 Paramiko SSH 库实现。

---

## 功能特性

### 核心部署能力
- **双模式部署**：支持本地 Windows 直接部署和远程 Linux SSH 部署
- **AI 智能部署计划**：集成 DeepSeek API，根据主机环境、项目配置、已有服务状态自动生成结构化部署步骤
- **AI 服务降级**：DeepSeek API 不可用时自动降级为预设默认部署计划，不阻塞部署流程
- **八步标准流程**：预检 -> 备份 -> 传输 -> 安装 -> 配置 -> 启动 -> 验证 -> 清理
- **三重验证**：进程存活检查 + 端口监听检查 + HTTP 200 健康检查
- **自动回滚**：部署失败时按反向顺序恢复备份文件并重启服务
- **部署锁机制**：同一主机不允许并发部署，避免资源冲突
- **任务取消**：支持取消进行中的部署任务（标志位 + 步骤间检查）
- **快速部署**：智能识别项目类型（Maven/Node/Jar/War/前端），自动填充 JDK/数据库配置，一键直达日志页
- **批量部署**：多项目按顺序依次部署到同一目标，自动串行避免锁冲突
- **增量传输**：基于 MD5 比对跳过未变更文件，重复部署耗时大幅缩短
- **部署后自定义脚本**：支持项目内 `.sh` 脚本或任意 Shell/Batch 命令，部署完成后自动执行
- **多环境配置模板**：内置 dev/test/pre/prod 四套模板（JVM/Nginx/MySQL/日志级别），支持自定义，部署时按环境自动合并

### 实时交互
- **WebSocket 日志推送**：部署过程日志实时推送到前端，支持颜色高亮和步骤进度
- **历史日志回看**：日志同时持久化到数据库，断线重连后自动补发历史日志
- **分片上传**：支持大文件（100MB+）分片上传和断点续传
- **每步确认模式**：可选每步确认执行或自动执行（仅危险操作确认）

### 主机管理
- **SSH 连接池**：基于 dict 缓存的连接池管理，连接复用，空闲自动清理
- **密码/密钥双认证**：支持 SSH 密码认证和私钥认证
- **主机信息采集**：自动采集 CPU、内存、磁盘、OS 信息和服务状态
- **连接测试**：一键测试 SSH 连接是否可达

### 监控告警
- **定时监控**：APScheduler 定时采集主机 CPU/内存/磁盘使用率和服务状态
- **AI 监控日报**：每日凌晨自动生成 AI 告警总结
- **钉钉通知**：部署结果和监控日报自动推送到钉钉群
- **阈值告警**：CPU/内存/磁盘超过阈值时触发告警
- **进程守护**：后台监控服务进程，异常退出自动重启（最多 3 次）并推送通知
- **磁盘智能管理**：自动清理过期备份/日志，支持 Web 一键清理
- **监控看板**：服务状态卡片 + 5 秒自动刷新

### AI 能力
- **多提供商**：支持 DeepSeek 云端 API 与 Ollama 本地模型（断网可用），Web 界面一键切换
- **AI 对话式运维**：右侧抽屉式对话助手，理解当前项目/主机/部署上下文
- **AI 配置优化**：按主机规格推荐 JVM/Nginx/MySQL 参数
- **AI 生成部署脚本**：生成含错误处理和回滚逻辑的 Shell/Batch 脚本

### 系统体验
- **暗色主题**：亮色/暗色/跟随系统三种模式
- **中英双语**：界面语言基础版切换（菜单与通用操作）
- **开机自启动**：Windows 注册表启动项，Web 界面开关
- **系统托盘**：可选 pystray 常驻托盘（`pip install pystray pillow` 后运行 `tray.bat`）
- **配置导出导入**：加密 JSON 导出全部主机/系统配置，新机一键恢复
- **自动备份**：每日自动备份 SQLite 数据库（保留 N 天），支持手动备份/恢复
- **数据清空**：一键清空部署记录/监控数据

### 安全特性
- **AES 加密存储**：主机密码、SSH 私钥、API Key 均 AES-256 加密后存储
- **JWT 认证**：登录后签发 JWT Token，所有 API 请求携带 Bearer Token
- **日志脱敏**：日志中不输出密码、密钥等敏感信息
- **路径安全**：文件操作防路径遍历攻击
- **危险命令检测**：识别 `rm -rf`、`del /f`、`shutdown`、`format` 等危险操作

---

## 环境要求

| 组件 | 最低版本 | 说明 |
|------|----------|------|
| 操作系统 | Windows 10/11 | 64 位系统 |
| Python | 3.10+ | 后端运行环境 |
| Node.js | 18+ | 前端构建环境 |
| npm | 随 Node.js 安装 | 前端包管理 |
| 磁盘空间 | 500MB+ | 包含依赖和运行时数据 |

### 可选组件（按需安装）
- **MySQL**：部署目标项目需要导入 SQL 时使用
- **Nginx**：本地部署前端静态资源时使用
- **Tomcat**：部署 WAR 包时使用
- **Redis**：目标项目依赖 Redis 时使用

以上组件请放置到 `tools/` 目录下（仅目录结构，不含实际软件包）。

---

## 快速启动

### 一键启动

1. 确保已安装 Python 3.10+ 和 Node.js 18+，并已加入系统 PATH
2. 双击执行 `start.bat`（或 在命令行中运行）
3. 脚本将自动完成以下操作：
   - 检查 Python 和 Node.js 环境
   - 安装 Python 依赖（`pip install -r mvp-agent/requirements.txt`）
   - 安装前端依赖并构建（`npm install && npm run build`）
   - 初始化 `.env` 配置文件（如不存在则从 `.env.example` 复制）
   - 创建 data 目录结构（db/deployments/backups/logs）
   - 初始化数据库（`python run.py --init-db`）
   - 启动 FastAPI 服务
4. 启动成功后，浏览器访问：**http://localhost:8080**
5. 使用默认账号登录：**admin / admin123**

### 停止服务

双击执行 `stop.bat`，或在服务运行窗口按 `Ctrl+C`。

停止脚本会自动查找并终止占用 8080 端口的进程。

### 手动启动（开发模式）

如需开发调试，可分别启动前后端：

**后端开发模式（热重载）：**
```bat
cd mvp-agent
pip install -r requirements.txt
python run.py --init-db
python run.py --reload
```

**前端开发模式（热重载）：**
```bat
cd mvp-frontend
npm install
npm run dev
```

前端开发模式访问地址：http://localhost:5173（API 自动代理到 8080）

---

## 部署包放置规范

部署包需放置到 `mvp-agent/data/deployments/{项目名}/` 目录下。每个项目目录应包含以下文件：

```
mvp-agent/data/deployments/{项目名}/
├── frontend.zip     # [可选] 前端构建产物压缩包（解压到 Nginx html 目录）
├── backend.jar      # [可选] 后端 JAR 包（或 backend.war WAR 包）
├── init.sql         # [可选] 数据库初始化 SQL 脚本
└── project.json     # [可选] 项目配置文件（缺失时从文件名推断）
```

> **说明**：`project.json` 为可选文件。如果缺失，系统会从文件名自动推断项目配置。
> 示例项目位于 `data/deployments/example-project/`，可参考其结构。

### project.json 示例格式

```json
{
  "name": "示例项目",
  "jdk_version": "8",
  "db_name": "example_db",
  "env_type": "dev",
  "frontend_port": 80,
  "backend_port": 8080
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 项目显示名称 |
| `jdk_version` | string | 否 | JDK 版本：`8` 或 `17`，默认 `8` |
| `db_name` | string | 否 | 数据库名称（有 init.sql 时使用） |
| `env_type` | string | 否 | 环境类型：`dev`（开发）或 `prod`（生产） |
| `frontend_port` | int | 否 | 前端服务端口，默认 80 |
| `backend_port` | int | 否 | 后端服务端口，默认 8080 |

---

## 操作步骤说明

### 1. 登录系统
- 访问 http://localhost:8080
- 输入默认账号 `admin` / 密码 `admin123` 登录
- 登录后进入 Dashboard 总览页面

### 2. 添加主机
- 进入「主机管理」页面
- 点击「添加主机」
- 填写主机信息：
  - **名称**：主机显示名称（如：生产服务器-01）
  - **IP 地址**：远程主机 IP 或 `127.0.0.1`（本地）
  - **端口**：SSH 端口，默认 22
  - **用户名**：SSH 登录用户名
  - **认证方式**：密码 或 密钥
  - **密码/私钥**：根据认证方式填写（AES 加密存储）
  - **是否本地**：勾选表示本地 Windows 主机
  - **JDK 版本**：8 或 17
  - **部署目录**：远程部署的目标目录
- 点击「测试连接」验证 SSH 连通性
- 点击「保存」完成添加

### 3. 部署向导
- 进入「部署向导」页面，按 5 步完成部署：

**步骤一：选择部署模式**
- 选择「本地部署」或「远程部署」
- 远程部署时下拉选择已添加的主机

**步骤二：选择项目**
- 系统自动扫描 `data/deployments/` 目录
- 卡片展示所有可用项目
- 支持上传新的部署包

**步骤三：配置部署参数**
- 环境类型：dev / prod
- JDK 版本：8 / 17
- 数据库名称（如有 init.sql）
- 执行模式：自动执行 / 每步确认
- 高级选项：端口配置

**步骤四：AI 部署预览**
- 调用 AI 生成部署计划
- 展示步骤列表，危险操作高亮显示
- 可查看 AI 建议和警告信息

**步骤五：执行与日志**
- WebSocket 实时日志推送
- 步骤进度条
- 三重验证结果展示
- 成功/失败操作按钮

### 4. 查看历史
- 进入「部署历史」页面
- 支持按状态/项目/主机/时间筛选
- 查看记录详情：完整日志、步骤时间线、AI 建议、回滚信息
- 一键回滚（仅当记录有备份时可用）
- 一键重新部署（基于历史记录配置）

### 5. 系统配置
- 进入「系统配置」页面
- **AI 配置**：DeepSeek API Key、Base URL、模型选择
- **钉钉配置**：Webhook URL、签名秘钥、测试推送
- **监控配置**：每日检查时间、CPU/内存/磁盘告警阈值
- **备份配置**：最大保留备份数量
- 配置修改后热更新生效，无需重启服务

---

## 常见问题

### Q1: 端口 8080 被占用怎么办？

**现象**：启动时提示 `Address already in use` 或 `[Errno 10048]`

**解决方案**：
1. 执行 `stop.bat` 终止占用进程
2. 或手动查找并终止：`netstat -ano | findstr :8080`，然后 `taskkill /F /PID <PID>`
3. 如需修改端口，编辑 `mvp-agent/.env` 文件中的 `APP_PORT`，同时修改 `start.bat` 和 `stop.bat` 中的端口号

### Q2: SSH 连接失败怎么办？

**现象**：测试连接时提示「SSH 连接失败」

**排查步骤**：
1. 确认远程主机 IP 和端口正确（默认 22）
2. 确认网络可达：`ping <主机IP>`
3. 确认 SSH 服务已启动：远程主机执行 `systemctl status sshd`
4. 确认用户名和密码正确
5. 确认防火墙未拦截 22 端口
6. 如使用密钥认证，确认私钥格式正确（PEM 格式）
7. 查看后端日志：`mvp-agent/data/logs/mvp-agent.log`

### Q3: AI 功能不可用怎么办？

**现象**：部署预览时提示「AI 不可用，已降级为默认计划」

**说明**：
- 这是**正常行为**，系统设计了 AI 降级机制
- 当 DeepSeek API Key 未配置或网络不可达时，自动使用预设默认部署计划
- 不会阻塞部署流程，所有功能仍可正常使用

**启用 AI 功能**：
1. 前往 https://platform.deepseek.com/ 注册并获取 API Key
2. 进入「系统配置」页面，填写 DeepSeek API Key
3. 点击「测试 AI」验证连通性
4. 或直接编辑 `mvp-agent/.env` 文件中的 `DEEPSEEK_API_KEY`

### Q4: 前端页面空白怎么办？

**现象**：访问 http://localhost:8080 页面空白

**解决方案**：
1. 确认前端已构建：检查 `mvp-frontend/dist/index.html` 是否存在
2. 重新执行 `start.bat`，或手动执行 `cd mvp-frontend && npm run build`
3. 检查浏览器控制台是否有 JS 错误
4. 清除浏览器缓存后重试

### Q5: 数据库初始化失败怎么办？

**现象**：`python run.py --init-db` 报错

**排查步骤**：
1. 确认 `mvp-agent/data/db/` 目录存在且有写权限
2. 删除旧的数据库文件：`mvp-agent/data/db/mvp.db*`（含 -wal、-shm）
3. 重新执行 `python run.py --init-db`
4. 查看错误日志定位具体原因

### Q6: 前端构建失败怎么办？

**现象**：`npm run build` 报错

**解决方案**：
1. 确认 Node.js 版本 >= 18：`node --version`
2. 删除 `node_modules` 和 `package-lock.json` 后重新安装：
   ```bat
   cd mvp-frontend
   rmdir /s /q node_modules
   del package-lock.json
   npm install
   npm run build
   ```
3. 如使用 npm 镜像源：`npm config set registry https://registry.npmmirror.com`

### Q7: 如何修改默认账号密码？

当前版本为固定账号 `admin/admin123`。如需修改：
1. 编辑 `mvp-agent/app/config/settings.py` 中的 `admin_username` 和 `admin_password` 默认值
2. 或在 `mvp-agent/.env` 中添加 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 环境变量
3. 重启服务生效

---

## API 文档

- **Swagger UI**：http://localhost:8080/docs
- **ReDoc**：http://localhost:8080/redoc
- **API 说明文档**：[docs/api.md](docs/api.md)

所有 API 接口前缀为 `/api/v1/`，认证方式为 JWT Bearer Token。

---

## 技术栈说明

### 后端（mvp-agent）

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 运行环境 |
| FastAPI | 0.109+ | Web 框架 |
| Uvicorn | 0.27+ | ASGI 服务器 |
| SQLAlchemy | 2.0+ | ORM 框架 |
| Pydantic | 2.5+ | 数据验证 |
| pydantic-settings | 2.1+ | 配置管理 |
| python-jose | - | JWT 签发与验证 |
| passlib | - | 密码哈希 |
| cryptography | 42.0+ | AES 加密（Fernet） |
| Paramiko | 3.4+ | SSH 远程操作 |
| openai | 1.12+ | DeepSeek API 调用（兼容 OpenAI 格式） |
| APScheduler | 3.10+ | 定时任务调度 |
| httpx | 0.27+ | 异步 HTTP 客户端（钉钉通知） |
| psutil | 5.9+ | 本地系统监控 |
| Jinja2 | 3.1+ | 部署脚本模板渲染 |
| PyYAML | 6.0+ | YAML 配置解析 |
| SQLite | - | 数据库（WAL 模式） |

### 前端（mvp-frontend）

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.x | 前端框架 |
| Vue Router | 4.x | 路由管理 |
| Pinia | - | 状态管理 |
| Element Plus | - | UI 组件库 |
| Axios | - | HTTP 请求 |
| Vite | - | 构建工具 |

### 架构特点

- **前后端一体化部署**：生产模式下 FastAPI 直接 mount 前端构建产物，单一端口提供服务
- **线程模型**：Paramiko 同步操作在独立线程执行，通过 `asyncio.run_coroutine_threadsafe` 桥接日志推送
- **SQLite WAL 模式**：提升并发读写性能，适配单 worker 部署
- **配置热更新**：系统配置变更后 AI/钉钉服务实时读取最新配置，无需重启

---

## 目录结构

```
mvp/
├── start.bat                      # Windows 一键启动脚本
├── stop.bat                       # 停止服务脚本
├── README.md                      # 使用说明（本文件）
│
├── mvp-agent/                     # Python 后端
│   ├── run.py                     # 启动入口
│   ├── requirements.txt           # Python 依赖
│   ├── .env                       # 环境变量（自动生成）
│   ├── .env.example               # 环境变量模板
│   ├── app/                       # 应用代码
│   │   ├── main.py                # FastAPI 应用入口
│   │   ├── config/                # 配置管理
│   │   ├── models/                # 数据模型
│   │   ├── schemas/               # 数据验证模型
│   │   ├── api/                   # API 路由
│   │   ├── core/                  # 核心引擎（部署、SSH、验证、回滚、安全）
│   │   ├── services/              # 服务层（AI、钉钉、监控、日志流）
│   │   ├── utils/                 # 工具函数
│   │   └── templates/             # Jinja2 部署脚本模板
│   └── data/                      # 运行时数据
│       ├── db/mvp.db              # SQLite 数据库
│       ├── deployments/           # 部署包目录
│       ├── backups/               # 部署备份
│       └── logs/                  # 运行日志
│
├── mvp-frontend/                  # Vue3 前端
│   ├── package.json
│   ├── vite.config.js
│   ├── dist/                      # 构建产物（自动生成）
│   └── src/
│       ├── views/                 # 页面组件
│       ├── components/            # 公共组件
│       ├── api/                   # API 调用
│       ├── stores/                # Pinia 状态
│       ├── composables/           # 组合式函数
│       ├── router/                # 路由配置
│       └── utils/                 # 工具函数
│
├── tools/                         # 本地部署工具目录
│   ├── nginx/
│   ├── tomcat/
│   ├── mysql/
│   └── redis/
│
├── data/                          # 示例部署包目录
│   └── deployments/
│       └── example-project/       # 示例项目
│           ├── project.json
│           └── init.sql
│
└── docs/
    └── api.md                     # API 文档说明
```
