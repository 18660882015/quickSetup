"""
多环境配置模板

内置 dev/test/pre/prod 四套模板，用户自定义模板保存在
data/env_templates.json（按项目规则不进 Git）。
部署时按 env_type 匹配模板，将 JVM/Nginx/MySQL/日志级别
参数合并进 project_config，引擎优先读取合并后的值。
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

from app.config.settings import DATA_DIR
from app.utils.logger import get_logger

logger = get_logger("env_template")

CUSTOM_TEMPLATES_FILE = DATA_DIR / "env_templates.json"

# 内置模板（不可删除，可被同名自定义模板覆盖）
BUILTIN_TEMPLATES: Dict[str, Dict] = {
    "dev": {
        "name": "dev",
        "label": "开发环境",
        "description": "小内存、DEBUG 日志，适合本地/联调",
        "jvm_args": "-Xms128m -Xmx512m -XX:MetaspaceSize=96m -XX:MaxMetaspaceSize=192m",
        "log_level": "DEBUG",
        "nginx": {"worker_processes": 1, "keepalive_timeout": 30},
        "mysql": {"max_connections": 100},
        "builtin": True,
    },
    "test": {
        "name": "test",
        "label": "测试环境",
        "description": "中等资源、INFO 日志，适合测试验证",
        "jvm_args": "-Xms256m -Xmx1g -XX:MetaspaceSize=128m -XX:MaxMetaspaceSize=256m",
        "log_level": "INFO",
        "nginx": {"worker_processes": 2, "keepalive_timeout": 45},
        "mysql": {"max_connections": 200},
        "builtin": True,
    },
    "pre": {
        "name": "pre",
        "label": "预发布环境",
        "description": "贴近生产的资源配置，INFO 日志",
        "jvm_args": "-Xms1g -Xmx2g -XX:MetaspaceSize=192m -XX:MaxMetaspaceSize=384m -XX:+UseG1GC",
        "log_level": "INFO",
        "nginx": {"worker_processes": 4, "keepalive_timeout": 60},
        "mysql": {"max_connections": 500},
        "builtin": True,
    },
    "prod": {
        "name": "prod",
        "label": "生产环境",
        "description": "大内存、G1GC、ERROR 日志，性能优先",
        "jvm_args": "-Xms2g -Xmx4g -XX:MetaspaceSize=256m -XX:MaxMetaspaceSize=512m -XX:+UseG1GC",
        "log_level": "ERROR",
        "nginx": {"worker_processes": "auto", "keepalive_timeout": 75},
        "mysql": {"max_connections": 1000},
        "builtin": True,
    },
}


def _load_custom_templates() -> Dict[str, Dict]:
    if not CUSTOM_TEMPLATES_FILE.exists():
        return {}
    try:
        with open(CUSTOM_TEMPLATES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"读取自定义环境模板失败: {e}")
        return {}


def _save_custom_templates(templates: Dict[str, Dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CUSTOM_TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)


def get_all_templates() -> List[Dict]:
    """所有模板：内置 + 自定义（自定义覆盖同名内置）"""
    merged = dict(BUILTIN_TEMPLATES)
    merged.update(_load_custom_templates())
    return list(merged.values())


def get_template(name: str) -> Optional[Dict]:
    """按名称获取模板（自定义优先）"""
    custom = _load_custom_templates()
    if name in custom:
        return custom[name]
    return BUILTIN_TEMPLATES.get(name)


def save_template(data: Dict) -> Dict:
    """保存自定义模板（同名覆盖）"""
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("模板名称不能为空")
    if not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("模板名称仅支持字母、数字、-、_")

    data = dict(data)
    data["name"] = name
    data["builtin"] = False

    templates = _load_custom_templates()
    templates[name] = data
    _save_custom_templates(templates)
    logger.info(f"保存环境模板: {name}")
    return data


def delete_template(name: str) -> bool:
    """删除自定义模板（内置模板不可删除）"""
    templates = _load_custom_templates()
    if name not in templates:
        if name in BUILTIN_TEMPLATES:
            raise ValueError("内置模板不可删除")
        return False
    del templates[name]
    _save_custom_templates(templates)
    logger.info(f"删除环境模板: {name}")
    return True


def apply_template_to_config(env_type: Optional[str], project_config: Dict) -> Dict:
    """将环境模板参数合并进项目配置（已有显式配置不覆盖）"""
    if not env_type:
        return project_config
    tpl = get_template(env_type)
    if not tpl:
        return project_config

    for key in ("jvm_args", "log_level"):
        if tpl.get(key) and not project_config.get(key):
            project_config[key] = tpl[key]

    for section in ("nginx", "mysql"):
        values = tpl.get(section) or {}
        merged = dict(project_config.get(section) or {})
        for k, v in values.items():
            merged.setdefault(k, v)
        if merged:
            project_config[section] = merged

    project_config["env_template_label"] = tpl.get("label", env_type)
    return project_config
