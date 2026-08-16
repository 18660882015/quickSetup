"""
智能项目识别服务

扫描项目目录，自动识别项目类型并推荐配置：
- pom.xml → Maven/Spring Boot 项目（解析 artifactId、java.version）
- package.json → Node.js 前端项目（解析 name、构建命令）
- application.yml/properties → Spring Boot 配置（解析数据库）
- Dockerfile → Docker 部署模式提示
- *.jar/*.war → Java 部署包
- dist//index.html → 前端静态资源
"""
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.config.settings import DEPLOYMENTS_DIR
from app.utils.logger import get_logger

logger = get_logger("project_detector")

# 忽略的目录
IGNORE_DIRS = {"node_modules", ".git", ".idea", "__pycache__", "target", ".vscode"}


def _parse_pom_xml(pom_path: Path) -> Dict:
    """解析 pom.xml 提取项目名和 Java 版本（轻量正则解析，避免额外依赖）"""
    try:
        content = pom_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"读取 pom.xml 失败: {e}")
        return {}

    result = {}
    # artifactId（取第一个非 parent 的）
    m = re.search(r"<artifactId>([^<]+)</artifactId>", content)
    if m:
        result["artifact_id"] = m.group(1).strip()
    # java.version 属性
    m = re.search(r"<java\.version>([^<]+)</java\.version>", content)
    if m:
        result["java_version"] = m.group(1).strip()
    else:
        m = re.search(r"<maven\.compiler\.(?:source|release)>([^<]+)</", content)
        if m:
            result["java_version"] = m.group(1).strip()
    # spring-boot 依赖检测
    if "spring-boot" in content:
        result["framework"] = "Spring Boot"
    # packaging
    m = re.search(r"<packaging>([^<]+)</packaging>", content)
    if m:
        result["packaging"] = m.group(1).strip()
    return result


def _parse_package_json(pkg_path: Path) -> Dict:
    """解析 package.json"""
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        logger.warning(f"解析 package.json 失败: {e}")
        return {}

    result = {"project_name": data.get("name", "")}
    scripts = data.get("scripts", {})
    if "build" in scripts:
        result["build_command"] = scripts["build"]
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    if "vue" in deps:
        result["framework"] = "Vue"
    elif "react" in deps:
        result["framework"] = "React"
    elif "express" in deps or "koa" in deps:
        result["framework"] = "Node 服务端"
    return result


def _parse_application_config(project_dir: Path) -> Dict:
    """解析 application.yml/properties 中的数据库配置"""
    candidates = []
    for name in ("application.yml", "application.yaml", "application.properties"):
        candidates.append(project_dir / name)
        candidates.append(project_dir / "src" / "main" / "resources" / name)

    for cfg in candidates:
        if not cfg.exists():
            continue
        try:
            content = cfg.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        result = {}
        m = re.search(r"(?:url|jdbcUrl)[=:]\s*jdbc:mysql://[^/]+/(\w+)", content)
        if m:
            result["db_name"] = m.group(1)
            result["db_type"] = "mysql"
        m = re.search(r"(?:server\.port|port)[=:]\s*(\d+)", content)
        if m:
            result["app_port"] = int(m.group(1))
        if result:
            return result
    return {}


def detect_project(project_dir: Path, max_depth: int = 3) -> Dict:
    """识别单个项目目录

    Returns:
        {
            "project_type": "maven" / "nodejs" / "jar" / "war" / "frontend" / "static" / "unknown",
            "framework": "Spring Boot" / "Vue" / ...,
            "project_name": 推荐项目名,
            "jdk_version": 推荐 JDK 版本,
            "build_command": 构建命令,
            "db_name": 数据库名,
            "app_port": 应用端口,
            "files": 部署相关文件列表,
            "recommendations": 推荐配置说明列表,
            "docker": 是否有 Dockerfile,
        }
    """
    result = {
        "project_type": "unknown",
        "framework": None,
        "project_name": project_dir.name,
        "jdk_version": None,
        "build_command": None,
        "db_name": None,
        "app_port": None,
        "files": [],
        "recommendations": [],
        "docker": False,
    }

    # 收集关键文件（限制深度）
    all_files: List[Path] = []
    for root, dirs, files in os.walk(project_dir):
        rel_depth = len(Path(root).relative_to(project_dir).parts)
        if rel_depth >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            all_files.append(Path(root) / f)

    file_names = {f.name for f in all_files}
    rel_files = [str(f.relative_to(project_dir)) for f in all_files]

    # Dockerfile 检测
    if "Dockerfile" in file_names:
        result["docker"] = True
        result["recommendations"].append("检测到 Dockerfile，可选择 Docker 部署模式")

    # 1. Maven 项目
    if "pom.xml" in file_names:
        pom_info = _parse_pom_xml(project_dir / "pom.xml")
        result["project_type"] = "maven"
        result["framework"] = pom_info.get("framework")
        if pom_info.get("artifact_id"):
            result["project_name"] = pom_info["artifact_id"]
        java_ver = pom_info.get("java_version")
        if java_ver:
            # 1.8 -> 8, 17 -> 17
            jdk = java_ver.split(".")[-1] if java_ver.startswith("1.") else java_ver
            result["jdk_version"] = jdk
            result["recommendations"].append(f"pom.xml 要求 Java {java_ver}，推荐 JDK {jdk}")
        result["build_command"] = "mvn clean package -DskipTests"
        result["recommendations"].append("Maven 项目，部署前建议执行 mvn clean package")

    # 2. Node.js 项目
    if "package.json" in file_names:
        pkg_info = _parse_package_json(project_dir / "package.json")
        if result["project_type"] == "unknown":
            result["project_type"] = "nodejs"
        if pkg_info.get("framework"):
            result["framework"] = pkg_info.get("framework") or result["framework"]
        if pkg_info.get("project_name"):
            result["project_name"] = pkg_info["project_name"]
        if pkg_info.get("build_command"):
            result["build_command"] = "npm install && npm run build"
            result["recommendations"].append("Node 项目，建议构建产物为 dist/ 目录")

    # 3. Spring Boot 配置（数据库、端口）
    if result["project_type"] in ("maven", "unknown"):
        app_cfg = _parse_application_config(project_dir)
        if app_cfg:
            result["db_name"] = app_cfg.get("db_name")
            result["app_port"] = app_cfg.get("app_port")
            if app_cfg.get("db_name"):
                result["recommendations"].append(
                    f"检测到数据库配置: {app_cfg['db_name']}，部署时将提示导入 SQL"
                )

    # 4. 部署包文件
    jars = [f for f in rel_files if f.endswith(".jar")]
    wars = [f for f in rel_files if f.endswith(".war")]
    sqls = [f for f in rel_files if f.endswith(".sql")]
    zips = [f for f in rel_files if f.endswith((".zip", ".tar.gz", ".tgz"))]
    has_dist = any(f.startswith("dist/") or f == "dist" for f in rel_files)
    has_index = "index.html" in file_names

    if jars:
        result["files"] = jars
        if result["project_type"] == "unknown":
            result["project_type"] = "jar"
            result["recommendations"].append("检测到 Jar 包，将按 Spring Boot Jar 方式部署")
    if wars:
        result["files"] = (result["files"] or []) + wars
        if result["project_type"] == "unknown":
            result["project_type"] = "war"
            result["recommendations"].append("检测到 War 包，将部署到 Tomcat webapps")
    if sqls:
        result["files"] = (result["files"] or []) + sqls
    if zips:
        result["files"] = (result["files"] or []) + zips

    if has_dist or (has_index and result["project_type"] in ("nodejs", "unknown")):
        if has_dist:
            result["frontend_dist"] = "dist"
            result["recommendations"].append("检测到 dist/ 目录，将作为前端静态资源部署到 Nginx")
        elif has_index:
            result["recommendations"].append("检测到 index.html，将作为静态站点部署")

    # 5. 类型兜底
    if result["project_type"] == "unknown":
        if result["files"]:
            result["project_type"] = "static"
            result["recommendations"].append("未识别出项目类型，按静态文件部署")
        else:
            result["recommendations"].append("未识别出已知项目类型，请手动配置部署参数")

    # jdk_version 保持 None 表示未识别，由调用方兜底
    # （避免覆盖 project.json / 主机配置中的显式值）
    if not result["jdk_version"] and result["project_type"] in ("maven", "jar", "war"):
        result["recommendations"].append("未识别到 JDK 版本要求，默认推荐 JDK 8")

    return result


def detect_all_projects() -> List[Dict]:
    """扫描 deployments 目录下所有项目并识别"""
    projects = []
    if not DEPLOYMENTS_DIR.exists():
        return projects

    for d in sorted(DEPLOYMENTS_DIR.iterdir()):
        if d.is_dir() and d.name not in IGNORE_DIRS:
            try:
                info = detect_project(d)
                info["dir_name"] = d.name
                projects.append(info)
            except Exception as e:
                logger.error(f"项目识别失败 [{d.name}]: {e}")
                projects.append({
                    "dir_name": d.name,
                    "project_name": d.name,
                    "project_type": "unknown",
                    "recommendations": [f"识别失败: {e}"],
                    "files": [],
                })
    return projects
