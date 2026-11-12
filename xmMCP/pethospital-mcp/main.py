# -*- coding: utf-8 -*-
"""
宠物医院 MCP Server - 第二期：list_pets + create_pet
基于 MCP 协议 2026-07-28，使用 Python MCP SDK v1.7.0+
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import time
from typing import Annotated, Literal, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# === 配置 ===
PETHOSPITAL_API_URL = os.getenv("PETHOSPITAL_API_URL", "http://127.0.0.1:8080").rstrip("/")
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8081"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")
API_TIMEOUT = float(os.getenv("PETHOSPITAL_TIMEOUT", "30"))
API_RETRIES = int(os.getenv("PETHOSPITAL_RETRIES", "2"))
RETRY_BACKOFF = float(os.getenv("PETHOSPITAL_RETRY_BACKOFF", "0.5"))
LOG_LEVEL = os.getenv("MCP_LOG_LEVEL", "INFO").upper()
PET_HOSPITAL_EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pethospital.exe")
PET_HOSPITAL_CWD = os.path.dirname(os.path.abspath(__file__))

# === 日志 ===
logger = logging.getLogger("pet_hospital_mcp")


def _setup_logging():
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    logger.propagate = False


# === 结构化错误 ===
class PetHospitalError(RuntimeError):
    """带错误码的业务异常。

    被 MCP SDK 捕获后，消息体是 JSON 字符串，模型能直接读到 code / message，
    不需要解析裸异常文本。
    """

    def __init__(self, code: str, message: str, detail: Optional[str] = None):
        self.code = code
        self.message = message
        self.detail = detail
        payload = {"code": code, "message": message}
        if detail:
            payload["detail"] = detail
        super().__init__(json.dumps(payload, ensure_ascii=False))


# === 确保 pethospital.exe 正在运行 ===
def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def _ensure_pethospital():
    if _is_port_open("127.0.0.1", 8080):
        logger.info("pethospital.exe 已在 8080 端口运行，直接复用")
        return
    if not os.path.exists(PET_HOSPITAL_EXE):
        logger.warning("未找到 pethospital.exe: %s", PET_HOSPITAL_EXE)
        return
    logger.info("正在启动 pethospital.exe ...")
    subprocess.Popen(
        [PET_HOSPITAL_EXE],
        cwd=PET_HOSPITAL_CWD,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        if _is_port_open("127.0.0.1", 8080):
            logger.info("pethospital.exe 已就绪")
            return
        time.sleep(0.2)
    logger.warning("pethospital.exe 未能启动，请检查")


# === Pydantic Schemas ===
class PetSummary(BaseModel):
    id: str
    name: str
    species: str
    breed: Optional[str] = None
    gender: Optional[str] = None
    ageMonths: Optional[int] = None
    color: Optional[str] = None
    ownerName: Optional[str] = None
    ownerPhone: Optional[str] = None
    doctor: Optional[str] = None
    disease: Optional[str] = None
    status: Optional[str] = None
    totalCost: Optional[float] = None
    visitCount: Optional[int] = None


class ListPetsOutput(BaseModel):
    items: list[PetSummary]
    total: int
    page: int
    pageSize: int


class CreatePetOutput(BaseModel):
    id: str
    name: str
    species: str
    breed: Optional[str] = None
    gender: Optional[str] = None
    ageMonths: Optional[int] = None
    ownerName: Optional[str] = None
    ownerPhone: Optional[str] = None
    doctor: Optional[str] = None
    disease: Optional[str] = None
    status: Optional[str] = None
    totalCost: Optional[float] = None
    visitCount: Optional[int] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


# === HTTP 客户端 ===
async def _request_json(
    tool_name: str,
    method: str,
    path: str,
    params: Optional[dict] = None,
    body: Optional[dict] = None,
) -> dict:
    """调用上游 REST API，失败时统一抛 PetHospitalError。

    GET 幂等请求按 PETHOSPITAL_RETRIES 做指数退避重试；POST 不重试，
    避免重复建档。每次调用都记录耗时与结果状态。
    """
    url = f"{PETHOSPITAL_API_URL}{path}"
    attempts = max(1, API_RETRIES + 1) if method == "GET" else 1
    started = time.perf_counter()
    last_error: Optional[PetHospitalError] = None

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.request(method, url, params=params, json=body)
            except httpx.TimeoutException as exc:
                last_error = PetHospitalError(
                    "UPSTREAM_TIMEOUT",
                    f"宠物医院接口超时（{API_TIMEOUT:g}s）：{url}",
                    str(exc),
                )
            except httpx.HTTPError as exc:
                last_error = PetHospitalError(
                    "UPSTREAM_UNAVAILABLE",
                    f"无法连接宠物医院接口：{url}",
                    str(exc),
                )
            else:
                if response.status_code >= 500:
                    last_error = PetHospitalError(
                        "UPSTREAM_HTTP_ERROR",
                        f"宠物医院接口返回 HTTP {response.status_code}",
                        response.text[:300],
                    )
                elif response.status_code >= 400:
                    # 4xx 属于请求本身的问题，重试无意义，直接失败
                    error = PetHospitalError(
                        "UPSTREAM_HTTP_ERROR",
                        f"宠物医院接口返回 HTTP {response.status_code}",
                        response.text[:300],
                    )
                    _log_failure(tool_name, path, started, error)
                    raise error
                else:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        error = PetHospitalError(
                            "UPSTREAM_BAD_PAYLOAD",
                            "宠物医院接口返回的不是合法 JSON",
                            response.text[:300],
                        )
                        _log_failure(tool_name, path, started, error)
                        raise error from exc
                    if not isinstance(payload, dict):
                        error = PetHospitalError(
                            "UPSTREAM_BAD_PAYLOAD",
                            "宠物医院接口返回的 JSON 不是对象",
                            json.dumps(payload, ensure_ascii=False)[:300],
                        )
                        _log_failure(tool_name, path, started, error)
                        raise error
                    logger.info(
                        "tool=%s path=%s status=ok http=%s attempt=%d elapsed=%.3fs",
                        tool_name,
                        path,
                        response.status_code,
                        attempt,
                        time.perf_counter() - started,
                    )
                    return payload

            if attempt < attempts:
                delay = RETRY_BACKOFF * (2 ** (attempt - 1))
                logger.warning(
                    "tool=%s path=%s code=%s attempt=%d/%d retry_in=%.2fs",
                    tool_name,
                    path,
                    last_error.code,
                    attempt,
                    attempts,
                    delay,
                )
                await asyncio.sleep(delay)

    _log_failure(tool_name, path, started, last_error)
    raise last_error  # type: ignore[misc]


def _log_failure(tool_name, path, started, error):
    logger.error(
        "tool=%s path=%s status=failed code=%s message=%s elapsed=%.3fs",
        tool_name,
        path,
        getattr(error, "code", "UNKNOWN"),
        getattr(error, "message", str(error)),
        time.perf_counter() - started,
    )


def _require_data(payload: dict, tool_name: str, path: str) -> dict:
    """校验上游响应结构，避免把不符合契约的数据直接塞给模型。"""
    data = payload.get("data")
    if not isinstance(data, dict):
        raise PetHospitalError(
            "UPSTREAM_BAD_PAYLOAD",
            "宠物医院接口响应缺少 data 对象",
            json.dumps(payload, ensure_ascii=False)[:300],
        )
    return data


async def fetch_pets(params: dict) -> ListPetsOutput:
    payload = await _request_json("list_pets", "GET", "/api/v1/pets", params=params)
    data = _require_data(payload, "list_pets", "/api/v1/pets")
    try:
        items = [PetSummary(**item) for item in data["items"]]
        return ListPetsOutput(
            items=items,
            total=int(data["total"]),
            page=int(data["page"]),
            pageSize=int(data["pageSize"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PetHospitalError(
            "UPSTREAM_BAD_PAYLOAD",
            "宠物医院列表响应字段不符合预期（需要 items/total/page/pageSize）",
            str(exc),
        ) from exc


async def create_pet_http(input_data: dict) -> CreatePetOutput:
    payload = await _request_json("create_pet", "POST", "/api/v1/pets", body=input_data)
    data = _require_data(payload, "create_pet", "/api/v1/pets")
    try:
        return CreatePetOutput(**data)
    except (TypeError, ValueError) as exc:
        raise PetHospitalError(
            "UPSTREAM_BAD_PAYLOAD",
            "宠物医院建档响应字段不符合预期",
            str(exc),
        ) from exc


# === 服务器初始化 ===
mcp = FastMCP(
    "pet-hospital",
    instructions="宠物医院管理系统 MCP Server，提供宠物档案查询和新增服务。",
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
)

# 注册 list_pets 工具：参数的类型、必填、范围与枚举都在 schema 中声明，
# 模型可以直接从 tools/list 读到约束，不依赖服务端二次猜测。
@mcp.tool()
async def list_pets(
    q: Annotated[
        Optional[str], Field(description="全文检索关键词，空格分词为 AND，同时匹配病历内容")
    ] = None,
    name: Annotated[Optional[str], Field(description="宠物姓名")] = None,
    ownerName: Annotated[Optional[str], Field(description="主人姓名")] = None,
    ownerPhone: Annotated[Optional[str], Field(description="主人电话")] = None,
    species: Annotated[
        Optional[str], Field(description="种类，例如 犬 / 猫 / 兔")
    ] = None,
    doctor: Annotated[Optional[str], Field(description="主治医生")] = None,
    disease: Annotated[Optional[str], Field(description="疾病名称")] = None,
    status: Annotated[
        Optional[str],
        Field(
            description="就诊状态：待就诊 / 就诊中 / 住院中 / 已康复 / 慢性病随访"
        ),
    ] = None,
    min_cost: Annotated[
        Optional[float], Field(ge=0, description="最低总花费（含）")
    ] = None,
    max_cost: Annotated[
        Optional[float], Field(ge=0, description="最高总花费（含）")
    ] = None,
    sort_by: Annotated[
        Optional[str],
        Field(description="排序字段，可选 name / totalCost / visitCount / createdAt"),
    ] = None,
    order: Annotated[
        Optional[Literal["asc", "desc"]], Field(description="排序方向 asc 或 desc")
    ] = None,
    page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
    page_size: Annotated[
        int, Field(ge=1, le=100, description="每页条数，1-100，默认 20")
    ] = 20,
) -> ListPetsOutput:
    """查询宠物档案列表。

    支持按种类 / 医生 / 状态 / 疾病 / 主人等维度筛选，并支持关键词全文检索、
    分页与排序；返回当前页的宠物档案与总数。
    """
    params = {
        "q": q,
        "name": name,
        "ownerName": ownerName,
        "ownerPhone": ownerPhone,
        "species": species,
        "doctor": doctor,
        "disease": disease,
        "status": status,
        "min": min_cost,
        "max": max_cost,
        "sortBy": sort_by,
        "order": order,
        "page": page,
        "pageSize": page_size,
    }
    return await fetch_pets(params)


@mcp.tool()
async def create_pet(
    name: Annotated[str, Field(min_length=1, description="宠物姓名")],
    species: Annotated[str, Field(min_length=1, description="种类，例如 犬 / 猫 / 兔")],
    breed: Annotated[Optional[str], Field(description="品种")] = None,
    gender: Annotated[
        Optional[Literal["公", "母"]], Field(description="性别，只能是 公 或 母")
    ] = None,
    ageMonths: Annotated[
        Optional[int], Field(ge=0, le=1200, description="月龄，0-1200")
    ] = None,
    ownerName: Annotated[Optional[str], Field(description="主人姓名")] = None,
    ownerPhone: Annotated[Optional[str], Field(description="主人电话")] = None,
    doctor: Annotated[Optional[str], Field(description="主治医生")] = None,
    disease: Annotated[Optional[str], Field(description="疾病名称")] = None,
    status: Annotated[
        Optional[str],
        Field(
            description="就诊状态：待就诊 / 就诊中 / 住院中 / 已康复 / 慢性病随访"
        ),
    ] = None,
) -> CreatePetOutput:
    """添加新动物档案。返回创建成功的宠物档案信息（含 id 与时间戳）。"""
    input_data = {
        "name": name,
        "species": species,
        "breed": breed,
        "gender": gender,
        "age_months": ageMonths,
        "ownerName": ownerName,
        "ownerPhone": ownerPhone,
        "doctor": doctor,
        "disease": disease,
        "status": status,
    }
    return await create_pet_http(
        {key: value for key, value in input_data.items() if value is not None}
    )


# === 启动 ===
if __name__ == "__main__":
    _setup_logging()
    _ensure_pethospital()
    logger.info(
        "MCP Server 启动：transport=%s host=%s port=%s upstream=%s",
        MCP_TRANSPORT,
        MCP_HOST,
        MCP_PORT,
        PETHOSPITAL_API_URL,
    )
    if MCP_TRANSPORT == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
