# MVP AI部署助手 - API 文档

## API 概述

所有 REST API 接口统一前缀为 `/api/v1/`，WebSocket 端点前缀为 `/ws/`。

- **Base URL**：`http://localhost:8080`
- **API 前缀**：`/api/v1/`
- **Swagger UI**：`http://localhost:8080/docs`
- **ReDoc**：`http://localhost:8080/redoc`

---

## 认证方式

### JWT Bearer Token

系统采用 JWT（JSON Web Token）进行身份认证。

1. 调用 `POST /api/v1/auth/login` 获取 Token
2. 后续所有请求在 Header 中携带：`Authorization: Bearer <token>`
3. Token 有效期 24 小时

**示例请求：**
```
GET /api/v1/hosts/ HTTP/1.1
Host: localhost:8080
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**认证失败响应（401）：**
```json
{
  "detail": "Could not validate credentials"
}
```

> 注意：`POST /api/v1/auth/login` 接口不需要 Token，其余接口均需要认证。

---

## 统一响应格式

所有接口统一返回以下 JSON 格式：

```json
{
  "code": 0,
  "msg": "success",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 状态码。`0` 表示成功，非 `0` 表示错误 |
| `msg` | string | 提示消息 |
| `data` | any | 响应数据，类型根据接口而定。失败时可能为 `null` |

**成功响应示例：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "id": 1,
    "name": "生产服务器"
  }
}
```

**错误响应示例：**
```json
{
  "code": 0,
  "msg": "主机不存在",
  "data": null
}
```

> 注意：HTTP 状态码为 404/400/401/409 等错误时，响应体为 FastAPI 默认格式 `{"detail": "错误描述"}`，而非统一响应格式。

---

## API 模块列表

| 模块 | 前缀 | 说明 |
|------|------|------|
| [认证](#1-认证模块) | `/api/v1/auth` | 登录、获取当前用户 |
| [主机管理](#2-主机管理模块) | `/api/v1/hosts` | 主机 CRUD、测试连接、采集信息 |
| [部署管理](#3-部署管理模块) | `/api/v1/deploy` | 部署计划、执行、查询、回滚、历史 |
| [文件管理](#4-文件管理模块) | `/api/v1/files` | 扫描、列表、上传、分片上传、删除 |
| [系统配置](#5-系统配置模块) | `/api/v1/configs` | 配置获取、更新、测试 AI、测试钉钉 |
| [监控管理](#6-监控管理模块) | `/api/v1/monitor` | 最新监控、历史、日报 |
| [WebSocket](#7-websocket-日志推送) | `/ws/logs/{task_id}` | 实时部署日志推送 |

---

## 1. 认证模块

### 1.1 用户登录

```
POST /api/v1/auth/login
```

验证用户名密码，签发 JWT Token。

**请求体：**
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "username": "admin",
    "role": "admin"
  }
}
```

**错误响应（401）：**
```json
{
  "detail": "用户名或密码错误"
}
```

---

### 1.2 获取当前用户信息

```
GET /api/v1/auth/me
```

获取当前登录用户信息。需要认证。

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "sub": "admin",
    "role": "admin"
  }
}
```

---

## 2. 主机管理模块

### 2.1 获取所有主机列表

```
GET /api/v1/hosts/
```

获取所有主机列表（不返回密码字段）。

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "id": 1,
      "name": "生产服务器-01",
      "ip": "192.168.1.100",
      "port": 22,
      "username": "root",
      "auth_type": "password",
      "jdk_version": "8",
      "deploy_dir": "/opt/deploy",
      "backup_dir": "/opt/backup",
      "status": "online",
      "is_local": false,
      "os_info": "Linux 5.4.0...",
      "cpu_info": "CPU核心数: 4...",
      "memory_info": "...",
      "disk_info": "...",
      "created_at": "2024-01-01T00:00:00",
      "updated_at": "2024-01-01T00:00:00"
    }
  ]
}
```

---

### 2.2 添加主机

```
POST /api/v1/hosts/
```

添加新主机，密码/私钥 AES 加密后存储。

**请求体：**
```json
{
  "name": "生产服务器-01",
  "ip": "192.168.1.100",
  "port": 22,
  "username": "root",
  "auth_type": "password",
  "jdk_version": "8",
  "deploy_dir": "/opt/deploy",
  "backup_dir": "/opt/backup",
  "is_local": false,
  "password": "your_ssh_password",
  "private_key": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 主机名称（最大100字符） |
| `ip` | string | 是 | IP 地址（最大45字符） |
| `port` | int | 否 | SSH 端口，默认 22（1-65535） |
| `username` | string | 否 | SSH 用户名，默认 root |
| `auth_type` | string | 否 | 认证方式：`password` 或 `key`，默认 password |
| `jdk_version` | string | 否 | JDK 版本：`8` 或 `17`，默认 8 |
| `deploy_dir` | string | 否 | 部署目录 |
| `backup_dir` | string | 否 | 备份目录 |
| `is_local` | bool | 否 | 是否本地主机，默认 false |
| `password` | string | 否 | SSH 密码（明文，存储时加密） |
| `private_key` | string | 否 | SSH 私钥（明文，存储时加密） |

**响应数据：** 返回创建的主机信息（不含密码），同 2.1 中的主机对象。

---

### 2.3 获取主机详情

```
GET /api/v1/hosts/{host_id}
```

获取指定主机详情（不返回密码）。

**路径参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `host_id` | int | 主机 ID |

---

### 2.4 更新主机信息

```
PUT /api/v1/hosts/{host_id}
```

更新主机信息，如提供密码则加密存储。所有字段均为可选（部分更新）。

**请求体（示例）：**
```json
{
  "name": "生产服务器-01-更新",
  "deploy_dir": "/data/app",
  "password": "new_password"
}
```

---

### 2.5 删除主机

```
DELETE /api/v1/hosts/{host_id}
```

删除主机，同时关闭对应的 SSH 连接。

---

### 2.6 测试主机连接

```
POST /api/v1/hosts/{host_id}/test
```

测试 SSH 连接是否成功。本地主机直接返回成功，远程主机创建临时 SSH 连接执行 `uname -a`。

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": true,
    "message": "SSH 连接成功: 192.168.1.100:22",
    "os_info": "Linux 5.4.0-xxx #1 SMP ..."
  }
}
```

---

### 2.7 采集主机参数信息

```
GET /api/v1/hosts/{host_id}/inspect
```

采集主机 CPU、内存、磁盘、OS 信息和服务状态。本地使用 psutil，远程使用 SSH 命令。

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": true,
    "message": "远程主机信息采集成功",
    "os_info": "Ubuntu 22.04 LTS...",
    "cpu_info": "CPU核心数: 4, CPU使用率: 15.3%",
    "memory_info": "Mem: 7.8G 3.2G 4.6G 41%",
    "disk_info": "/dev/sda1: 50G 30G 20G 60%"
  }
}
```

---

## 3. 部署管理模块

### 3.1 生成部署计划

```
POST /api/v1/deploy/plan
```

调用 AI 生成部署计划（预览模式）。AI 不可用时自动降级为默认计划。

**请求体：**
```json
{
  "host_id": 1,
  "project_name": "example-project",
  "env_type": "dev",
  "jdk_version": "8",
  "db_name": "example_db",
  "execute_mode": "auto",
  "is_local": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `host_id` | int | 否 | 主机 ID（本地部署可空） |
| `project_name` | string | 是 | 项目名称 |
| `env_type` | string | 否 | 环境类型：`dev` 或 `prod`，默认 prod |
| `jdk_version` | string | 否 | JDK 版本：`8` 或 `17`，默认 8 |
| `db_name` | string | 否 | 数据库名 |
| `execute_mode` | string | 否 | 执行模式：`auto` 或 `step_by_step`，默认 auto |
| `is_local` | bool | 否 | 是否本地部署，默认 false |

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "project_name": "example-project",
    "env_type": "dev",
    "jdk_version": "8",
    "steps": [
      {
        "step": "precheck",
        "name": "预检",
        "description": "检查磁盘空间、端口占用、已有服务状态",
        "command": "df -h && netstat -tlnp",
        "is_dangerous": false,
        "estimated_time": 5
      },
      {
        "step": "backup",
        "name": "备份",
        "description": "备份当前版本配置和文件",
        "command": "tar -czf /opt/backup/...",
        "is_dangerous": false,
        "estimated_time": 10
      }
    ],
    "ai_suggestion": "建议先停止旧版本服务再进行部署...",
    "warnings": ["将导入 SQL 到数据库: example_db"]
  }
}
```

---

### 3.2 执行部署

```
POST /api/v1/deploy/execute
```

启动部署任务，创建部署记录并在后台线程执行。

**请求体：**
```json
{
  "host_id": 1,
  "project_name": "example-project",
  "env_type": "dev",
  "jdk_version": "8",
  "db_name": "example_db",
  "execute_mode": "auto",
  "is_local": false,
  "deploy_dir": "/opt/deploy",
  "version": "v1.0.0"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `host_id` | int | 否 | 主机 ID |
| `project_name` | string | 是 | 项目名称 |
| `env_type` | string | 否 | 环境类型，默认 prod |
| `jdk_version` | string | 否 | JDK 版本，默认 8 |
| `db_name` | string | 否 | 数据库名 |
| `execute_mode` | string | 否 | 执行模式，默认 auto |
| `is_local` | bool | 否 | 是否本地部署 |
| `deploy_dir` | string | 否 | 部署目录 |
| `version` | string | 否 | 版本号 |

**响应数据：**
```json
{
  "code": 0,
  "msg": "部署任务已创建，正在后台执行",
  "data": {
    "task_id": 1,
    "status": "pending"
  }
}
```

**错误响应（409 - 部署锁）：**
```json
{
  "detail": "主机已有部署任务进行中 (task_id=1)，请等待完成或取消后重试"
}
```

> 部署执行后，使用返回的 `task_id` 连接 WebSocket 获取实时日志：`/ws/logs/{task_id}`

---

### 3.3 查询部署任务状态

```
GET /api/v1/deploy/task/{task_id}
```

查询指定部署任务的状态和详情。

**路径参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | int | 部署任务 ID |

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "id": 1,
    "host_id": 1,
    "project_name": "example-project",
    "env_type": "dev",
    "execute_status": "success",
    "execute_mode": "auto",
    "jdk_version": "8",
    "db_name": "example_db",
    "log_path": null,
    "backup_path": "/opt/backup/20240101_120000",
    "version": "v1.0.0",
    "steps_detail": [
      {"step": "precheck", "status": "success", "duration": 3.2},
      {"step": "backup", "status": "success", "duration": 8.5}
    ],
    "logs": "[INFO] 部署任务已启动...\n[SUCCESS] 部署成功",
    "ai_suggestion": null,
    "rollback_info": null,
    "started_at": "2024-01-01T12:00:00",
    "finished_at": "2024-01-01T12:05:00",
    "duration": 300.0,
    "error_message": null,
    "operator": "admin",
    "can_rollback": true,
    "created_at": "2024-01-01T12:00:00"
  }
}
```

**部署状态（execute_status）说明：**
| 状态 | 说明 |
|------|------|
| `pending` | 待执行 |
| `running` | 执行中 |
| `success` | 成功 |
| `failed` | 失败 |
| `rolled_back` | 已回滚 |
| `cancelled` | 已取消 |

---

### 3.4 回滚部署

```
POST /api/v1/deploy/rollback/{record_id}
```

回滚到指定部署版本。流程：停止服务 -> 恢复备份文件 -> 重启 -> 验证。

**路径参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `record_id` | int | 部署记录 ID |

**响应数据：**
```json
{
  "code": 0,
  "msg": "回滚任务已启动，正在后台执行",
  "data": {
    "record_id": 1,
    "status": "rolling_back"
  }
}
```

**错误响应（400）：**
```json
{
  "detail": "该部署记录不支持回滚（无备份或已回滚）"
}
```

---

### 3.5 获取部署历史

```
GET /api/v1/deploy/history
```

获取部署历史列表，支持按主机、项目、状态过滤和分页。

**查询参数：**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `host_id` | int | - | 按主机 ID 过滤 |
| `project_name` | string | - | 按项目名过滤（模糊匹配） |
| `status` | string | - | 按状态过滤（pending/running/success/failed/rolled_back/cancelled） |
| `limit` | int | 20 | 返回数量（1-100） |
| `offset` | int | 0 | 偏移量 |

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "list": [
      {
        "id": 1,
        "host_id": 1,
        "project_name": "example-project",
        "execute_status": "success",
        "operator": "admin",
        "created_at": "2024-01-01T12:00:00",
        "duration": 300.0,
        "can_rollback": true
      }
    ],
    "total": 1
  }
}
```

---

## 4. 文件管理模块

### 4.1 扫描部署包目录

```
GET /api/v1/files/scan
```

扫描 `data/deployments/` 目录，列出所有可用项目。

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "name": "example-project",
      "path": "data/deployments/example-project",
      "files": ["project.json", "init.sql"],
      "file_count": 2,
      "has_config": true
    }
  ]
}
```

---

### 4.2 列出项目文件

```
GET /api/v1/files/list?project={project_name}
```

列出指定项目下的文件列表。

**查询参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `project` | string | 项目名。为空时列出所有项目目录 |

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "name": "project.json",
      "size": 156,
      "size_str": "156 B",
      "is_dir": false,
      "modified": "2024-01-01T12:00:00"
    }
  ]
}
```

---

### 4.3 上传文件

```
POST /api/v1/files/upload
```

上传文件到指定项目目录（基础上传，适合小文件）。使用 `multipart/form-data`。

**请求参数（Form）：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | 上传的文件 |
| `project` | string | 否 | 项目名（为空时上传到根目录） |

**响应数据：**
```json
{
  "code": 0,
  "msg": "文件上传成功",
  "data": {
    "filename": "backend.jar",
    "path": "data/deployments/example-project/backend.jar",
    "size": 52428800,
    "size_str": "50.0 MB"
  }
}
```

---

### 4.4 分片上传

```
POST /api/v1/files/upload/chunk
```

分片上传接口，支持 100MB+ 大文件和断点续传。前端分片大小建议 5MB。

**请求参数（Form）：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | 当前分片文件 |
| `chunkIndex` | int | 是 | 当前分片索引（从 0 开始） |
| `totalChunks` | int | 是 | 总分片数 |
| `chunkHash` | string | 是 | 当前分片 hash（用于校验） |
| `fileHash` | string | 是 | 文件唯一标识（用于断点续传） |
| `filename` | string | 是 | 文件名 |
| `project` | string | 否 | 项目名 |

**响应数据：**
```json
{
  "code": 0,
  "msg": "分片 1/10 上传成功",
  "data": {
    "chunkIndex": 0,
    "totalChunks": 10,
    "fileHash": "abc123...",
    "filename": "backend.jar",
    "skipped": false
  }
}
```

> 如果分片已存在（断点续传），`skipped` 为 `true`。

---

### 4.5 合并分片

```
POST /api/v1/files/upload/merge
```

合并已上传的分片为完整文件。

**请求参数（Form）：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `fileHash` | string | 是 | 文件唯一标识 |
| `filename` | string | 是 | 文件名 |
| `totalChunks` | int | 是 | 总分片数 |
| `project` | string | 否 | 项目名 |

**响应数据：**
```json
{
  "code": 0,
  "msg": "文件合并成功",
  "data": {
    "filename": "backend.jar",
    "path": "data/deployments/example-project/backend.jar",
    "size": 52428800,
    "size_str": "50.0 MB",
    "totalChunks": 10
  }
}
```

---

### 4.6 查询分片上传状态

```
GET /api/v1/files/upload/status?fileHash={fileHash}
```

查询分片上传状态，用于断点续传。返回已上传的分片索引列表。

**查询参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `fileHash` | string | 文件唯一标识 |

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "fileHash": "abc123...",
    "uploadedChunks": [0, 1, 2, 3],
    "count": 4
  }
}
```

---

### 4.7 删除文件

```
DELETE /api/v1/files/{path}
```

删除文件或目录。path 为相对于 `data/deployments/` 的路径。

**路径参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `path` | string | 相对于 deployments 目录的路径 |

**响应数据：**
```json
{
  "code": 0,
  "msg": "删除成功",
  "data": null
}
```

---

## 5. 系统配置模块

### 5.1 获取所有系统配置

```
GET /api/v1/configs/
```

获取所有系统配置。加密字段返回掩码 `****`。

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "id": 1,
      "config_key": "deepseek_api_key",
      "config_value": "****",
      "is_encrypted": true,
      "description": "DeepSeek API Key",
      "updated_at": "2024-01-01T12:00:00"
    },
    {
      "id": 2,
      "config_key": "deepseek_model",
      "config_value": "deepseek-chat",
      "is_encrypted": false,
      "description": "DeepSeek 模型名称",
      "updated_at": "2024-01-01T12:00:00"
    }
  ]
}
```

**系统配置项列表：**
| 配置键 | 加密 | 默认值 | 说明 |
|--------|------|--------|------|
| `deepseek_api_key` | 是 | - | DeepSeek API Key |
| `deepseek_base_url` | 否 | `https://api.deepseek.com` | DeepSeek API 地址 |
| `deepseek_model` | 否 | `deepseek-chat` | DeepSeek 模型名 |
| `dingtalk_webhook` | 是 | - | 钉钉 Webhook URL |
| `dingtalk_secret` | 是 | - | 钉钉签名秘钥 |
| `dingtalk_enabled` | 否 | `false` | 是否启用钉钉通知 |
| `monitor_time` | 否 | `02:00` | 每日监控时间 |
| `cpu_threshold` | 否 | `80` | CPU 告警阈值（%） |
| `memory_threshold` | 否 | `80` | 内存告警阈值（%） |
| `disk_threshold` | 否 | `90` | 磁盘告警阈值（%） |
| `backup_max_count` | 否 | `5` | 最大备份保留数量 |
| `deploy_timeout` | 否 | `300` | 部署超时时间（秒） |

---

### 5.2 更新指定配置

```
PUT /api/v1/configs/{config_key}
```

更新指定配置项。如果是加密字段，值将 AES 加密后存储。配置热更新，无需重启。

**路径参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `config_key` | string | 配置键名 |

**请求体：**
```json
{
  "config_value": "sk-your-api-key-here",
  "is_encrypted": true
}
```

---

### 5.3 测试 AI 接口连通性

```
POST /api/v1/configs/test-ai
```

测试 DeepSeek AI 接口连通性。从 sys_configs 读取最新 API Key 和模型配置。

**请求体：**
```json
{
  "message": "你好，请回复：AI 服务正常"
}
```

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": true,
    "message": "AI 连接测试成功",
    "reply": "AI 服务正常"
  }
}
```

---

### 5.4 测试钉钉推送

```
POST /api/v1/configs/test-dingtalk
```

测试钉钉机器人推送。从 sys_configs 读取最新 Webhook URL 和签名秘钥。

**请求体：**
```json
{
  "message": "钉钉推送测试"
}
```

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": true,
    "message": "钉钉推送成功"
  }
}
```

---

## 6. 监控管理模块

### 6.1 获取所有主机最新监控数据

```
GET /api/v1/monitor/latest
```

获取每台主机最近一次采集的监控数据。

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "id": 1,
      "host_id": 1,
      "host_name": "生产服务器-01",
      "check_date": "2024-01-01",
      "tomcat_status": "running",
      "nginx_status": "running",
      "mysql_status": "running",
      "redis_status": "stopped",
      "cpu_usage": 25.3,
      "memory_usage": 45.2,
      "disk_usage": 60.0,
      "error_log_count": 3,
      "ai_alert_summary": "Redis 服务未运行，建议检查...",
      "dingtalk_pushed": true,
      "created_at": "2024-01-01T02:00:00"
    }
  ]
}
```

---

### 6.2 获取主机监控历史

```
GET /api/v1/monitor/history/{host_id}
```

获取指定主机的监控历史数据。

**路径参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `host_id` | int | 主机 ID |

**查询参数：**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `days` | int | 7 | 查询天数（1-90） |

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "host_id": 1,
    "host_name": "生产服务器-01",
    "days": 7,
    "start_date": "2023-12-25",
    "end_date": "2024-01-01",
    "records": [],
    "total": 7
  }
}
```

---

### 6.3 获取最新日报

```
GET /api/v1/monitor/daily-report
```

获取最新的监控日报，包含所有主机最新监控数据和 AI 告警总结。

**响应数据：**
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "check_date": "2024-01-01",
    "records": [],
    "ai_summary": "今日发现 1 台主机 Redis 服务异常，建议尽快处理...",
    "dingtalk_pushed": true,
    "total": 3
  }
}
```

---

## 7. WebSocket 日志推送

### 7.1 部署日志流

```
WS /ws/logs/{task_id}
```

实时推送部署任务的日志和状态。连接后会自动补发历史日志。

**路径参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | int | 部署任务 ID |

**服务端推送消息格式：**
```json
{
  "type": "log",
  "level": "info",
  "message": "部署任务已启动 (task_id=1)",
  "step": "start",
  "timestamp": "2024-01-01T12:00:00.000000"
}
```

**消息类型（type）：**
| 类型 | 说明 |
|------|------|
| `log` | 日志消息 |
| `status` | 状态变更（连接成功、部署完成等） |
| `progress` | 进度更新 |

**日志级别（level）：**
| 级别 | 颜色 | 说明 |
|------|------|------|
| `info` | 蓝色 | 信息 |
| `warn` | 黄色 | 警告 |
| `error` | 红色 | 错误 |
| `success` | 绿色 | 成功 |

**客户端可发送的消息：**
| 消息 | 说明 |
|------|------|
| `ping` | 心跳，服务端回复 `pong` |
| `{"type": "cancel"}` | 取消部署任务 |

**连接示例（JavaScript）：**
```javascript
const ws = new WebSocket('ws://localhost:8080/ws/logs/1');
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    console.log(`[${msg.level}] ${msg.message}`);
};
// 心跳
setInterval(() => ws.send('ping'), 30000);
// 取消部署
ws.send(JSON.stringify({ type: 'cancel' }));
```

---

## 错误码说明

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 401 | 未认证或 Token 失效 |
| 404 | 资源不存在 |
| 409 | 资源冲突（如部署锁） |
| 500 | 服务器内部错误 |

> 统一响应中 `code` 字段：`0` 表示成功，`-1` 表示一般错误。HTTP 4xx/5xx 错误使用 FastAPI 默认格式 `{"detail": "..."}`。

---

## 完整调用示例

### 登录并获取主机列表

```bash
# 1. 登录获取 Token
curl -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'

# 2. 使用 Token 获取主机列表
curl http://localhost:8080/api/v1/hosts/ \
  -H "Authorization: Bearer <your_token>"
```

### 上传部署包

```bash
# 上传 JAR 包到项目目录
curl -X POST http://localhost:8080/api/v1/files/upload?project=example-project \
  -H "Authorization: Bearer <your_token>" \
  -F "file=@backend.jar"
```

### 生成部署计划并执行

```bash
# 1. 生成部署计划
curl -X POST http://localhost:8080/api/v1/deploy/plan \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "host_id": 1,
    "project_name": "example-project",
    "env_type": "dev",
    "jdk_version": "8",
    "db_name": "example_db",
    "is_local": false
  }'

# 2. 执行部署
curl -X POST http://localhost:8080/api/v1/deploy/execute \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "host_id": 1,
    "project_name": "example-project",
    "env_type": "dev",
    "jdk_version": "8",
    "db_name": "example_db",
    "execute_mode": "auto",
    "is_local": false,
    "version": "v1.0.0"
  }'

# 3. 查询部署状态
curl http://localhost:8080/api/v1/deploy/task/1 \
  -H "Authorization: Bearer <your_token>"
```
