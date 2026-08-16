"""
文件管理 API：扫描、列表、上传、分片上传、删除

P2 实现：
- POST /upload: 基础上传（multipart）
- POST /upload/chunk: 分片上传接口（支持 100MB+ 文件）
- POST /upload/merge: 合并分片
- GET /scan: 扫描部署包目录
- GET /list: 列出项目下文件
- DELETE /{path}: 删除文件

前端分片大小 5MB，支持断点续传。
"""
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Form
from fastapi.responses import JSONResponse

from app.config.settings import DEPLOYMENTS_DIR, DATA_DIR
from app.core.security import get_current_user
from app.schemas.common import ApiResponse, success
from app.utils.file_utils import (
    scan_deployments,
    list_directory,
    delete_file,
    get_file_size_str,
)
from app.utils.logger import get_logger

logger = get_logger("api.files")

router = APIRouter(prefix="/files", tags=["文件管理"])

# 分片上传临时目录
CHUNKS_DIR = DATA_DIR / "chunks"


@router.get("/scan", response_model=ApiResponse, summary="扫描部署包目录")
def scan(
    _: dict = Depends(get_current_user),
):
    """扫描 data/deployments/ 目录，列出所有可用项目"""
    projects = scan_deployments()
    return success(data=projects)


@router.get("/list", response_model=ApiResponse, summary="列出项目下文件")
def list_files(
    project: Optional[str] = None,
    _: dict = Depends(get_current_user),
):
    """列出指定项目下的文件列表

    - project 为空时列出所有项目目录
    - project 指定时列出该项目下的文件
    """
    if not DEPLOYMENTS_DIR.exists():
        DEPLOYMENTS_DIR.mkdir(parents=True, exist_ok=True)
        return success(data=[])

    if project:
        target = DEPLOYMENTS_DIR / project
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"项目目录不存在: {project}")
        files = list_directory(target)
    else:
        files = list_directory(DEPLOYMENTS_DIR)

    return success(data=files)


@router.post("/upload", response_model=ApiResponse, summary="上传文件")
async def upload_file(
    file: UploadFile = File(...),
    project: Optional[str] = None,
    _: dict = Depends(get_current_user),
):
    """上传文件到指定项目目录（基础上传，适合小文件）

    - project 指定项目名，文件上传到 data/deployments/{project}/
    - project 为空时上传到 data/deployments/
    - 大文件请使用 /upload/chunk + /upload/merge 分片上传
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")

    # 构建目标目录
    target_dir = DEPLOYMENTS_DIR
    if project:
        target_dir = DEPLOYMENTS_DIR / project
    target_dir.mkdir(parents=True, exist_ok=True)

    file_path = target_dir / file.filename

    # 写入文件
    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        logger.error(f"文件上传失败: {file.filename}, 错误: {e}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {e}")

    file_size = file_path.stat().st_size
    logger.info(f"文件上传成功: {file_path} ({get_file_size_str(file_size)})")

    return success(
        data={
            "filename": file.filename,
            "path": str(file_path),
            "size": file_size,
            "size_str": get_file_size_str(file_size),
        },
        msg="文件上传成功",
    )


# ======================================================================
# 分片上传
# ======================================================================
@router.post("/upload/chunk", response_model=ApiResponse, summary="分片上传")
async def upload_chunk(
    file: UploadFile = File(...),
    chunkIndex: int = Form(..., description="当前分片索引（从0开始）"),
    totalChunks: int = Form(..., description="总分片数"),
    chunkHash: str = Form(..., description="当前分片hash（用于校验）"),
    fileHash: str = Form(..., description="文件唯一标识（用于断点续传）"),
    filename: str = Form(..., description="文件名"),
    project: Optional[str] = Form(default=None, description="项目名"),
    _: dict = Depends(get_current_user),
):
    """分片上传接口（支持 100MB+ 文件）

    前端分片大小建议 5MB，支持断点续传。

    流程：
    1. 前端将大文件切割为多个 5MB 分片
    2. 逐个上传分片到 /upload/chunk
    3. 所有分片上传完成后调用 /upload/merge 合并
    4. 断点续传：通过 fileHash 标识，已上传的分片跳过
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")

    # 确保分片目录存在
    # 每个 fileHash 对应一个临时目录
    upload_id = fileHash
    chunk_dir = CHUNKS_DIR / upload_id
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # 检查分片是否已存在（断点续传）
    chunk_file = chunk_dir / f"{chunkIndex}.part"
    if chunk_file.exists():
        logger.info(f"分片已存在，跳过: file={filename}, chunk={chunkIndex}/{totalChunks}")
        return success(
            data={
                "chunkIndex": chunkIndex,
                "totalChunks": totalChunks,
                "fileHash": fileHash,
                "filename": filename,
                "skipped": True,
            },
            msg="分片已存在，跳过上传",
        )

    # 写入分片
    try:
        content = await file.read()
        with open(chunk_file, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"分片上传失败: file={filename}, chunk={chunkIndex}, error={e}")
        raise HTTPException(status_code=500, detail=f"分片上传失败: {e}")

    logger.info(
        f"分片上传成功: file={filename}, chunk={chunkIndex}/{totalChunks}, "
        f"size={get_file_size_str(len(content))}"
    )

    return success(
        data={
            "chunkIndex": chunkIndex,
            "totalChunks": totalChunks,
            "fileHash": fileHash,
            "filename": filename,
            "skipped": False,
        },
        msg=f"分片 {chunkIndex + 1}/{totalChunks} 上传成功",
    )


@router.post("/upload/merge", response_model=ApiResponse, summary="合并分片")
async def merge_chunks(
    fileHash: str = Form(..., description="文件唯一标识"),
    filename: str = Form(..., description="文件名"),
    totalChunks: int = Form(..., description="总分片数"),
    project: Optional[str] = Form(default=None, description="项目名"),
    _: dict = Depends(get_current_user),
):
    """合并已上传的分片

    流程：
    1. 检查所有分片是否完整
    2. 按顺序合并分片为完整文件
    3. 移动到目标目录
    4. 清理临时分片
    """
    chunk_dir = CHUNKS_DIR / fileHash

    if not chunk_dir.exists():
        raise HTTPException(status_code=404, detail="分片数据不存在，请重新上传")

    # 检查分片完整性
    missing_chunks = []
    for i in range(totalChunks):
        chunk_file = chunk_dir / f"{i}.part"
        if not chunk_file.exists():
            missing_chunks.append(i)

    if missing_chunks:
        raise HTTPException(
            status_code=400,
            detail=f"分片不完整，缺少: {missing_chunks}",
        )

    # 构建目标路径
    target_dir = DEPLOYMENTS_DIR
    if project:
        target_dir = DEPLOYMENTS_DIR / project
    target_dir.mkdir(parents=True, exist_ok=True)

    target_file = target_dir / filename

    # 合并分片
    try:
        with open(target_file, "wb") as out_f:
            for i in range(totalChunks):
                chunk_file = chunk_dir / f"{i}.part"
                with open(chunk_file, "rb") as in_f:
                    out_f.write(in_f.read())
    except Exception as e:
        logger.error(f"合并分片失败: file={filename}, error={e}")
        raise HTTPException(status_code=500, detail=f"合并分片失败: {e}")

    # 清理临时分片
    try:
        shutil.rmtree(chunk_dir)
    except Exception as e:
        logger.warning(f"清理临时分片失败: {e}")

    file_size = target_file.stat().st_size
    logger.info(
        f"分片合并完成: {target_file} ({get_file_size_str(file_size)}), "
        f"共 {totalChunks} 个分片"
    )

    return success(
        data={
            "filename": filename,
            "path": str(target_file),
            "size": file_size,
            "size_str": get_file_size_str(file_size),
            "totalChunks": totalChunks,
        },
        msg="文件合并成功",
    )


@router.get("/upload/status", response_model=ApiResponse, summary="查询分片上传状态")
def check_upload_status(
    fileHash: str,
    _: dict = Depends(get_current_user),
):
    """查询分片上传状态（用于断点续传）

    返回已上传的分片索引列表
    """
    chunk_dir = CHUNKS_DIR / fileHash

    if not chunk_dir.exists():
        return success(data={"fileHash": fileHash, "uploadedChunks": []})

    uploaded_chunks = []
    for chunk_file in chunk_dir.glob("*.part"):
        try:
            index = int(chunk_file.stem)
            uploaded_chunks.append(index)
        except ValueError:
            continue

    uploaded_chunks.sort()

    return success(
        data={
            "fileHash": fileHash,
            "uploadedChunks": uploaded_chunks,
            "count": len(uploaded_chunks),
        }
    )


@router.delete("/{path:path}", response_model=ApiResponse, summary="删除文件")
def delete_file_api(
    path: str,
    _: dict = Depends(get_current_user),
):
    """删除文件或目录

    path 为相对于 data/deployments/ 的路径
    """
    # 安全检查：防止路径遍历攻击
    target = (DEPLOYMENTS_DIR / path).resolve()
    try:
        target.relative_to(DEPLOYMENTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="非法路径")

    if not target.exists():
        raise HTTPException(status_code=404, detail="文件或目录不存在")

    if delete_file(str(target)):
        return success(msg="删除成功")
    else:
        raise HTTPException(status_code=500, detail="删除失败")
