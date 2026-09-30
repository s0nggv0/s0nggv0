# -*- coding: utf-8 -*-
"""
宠物医院 MCP Server - 第二期：list_pets + create_pet
基于 MCP 协议 2026-07-28，使用 Python MCP SDK v1.7.0+
"""

import os
import sys
import subprocess
import socket
import time
import httpx
from pydantic import BaseModel, Field
from typing import Optional
from mcp.server.fastmcp import FastMCP

# === 配置 ===
PETHOSPITAL_API_URL = os.getenv("PETHOSPITAL_API_URL", "http://127.0.0.1:8080")
MCP_PORT = int(os.getenv("MCP_PORT", "8081"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http")
PET_HOSPITAL_EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pethospital.exe")
PET_HOSPITAL_CWD = os.path.dirname(os.path.abspath(__file__))

# === 确保 pethospital.exe 正在运行 ===
def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError):
        return False

def _ensure_pethospital():
    if _is_port_open("127.0.0.1", 8080):
        return
    if not os.path.exists(PET_HOSPITAL_EXE):
        print(f"[pet-hospital MCP] 警告: 未找到 pethospital.exe: {PET_HOSPITAL_EXE}", file=sys.stderr)
        return
    print(f"[pet-hospital MCP] 正在启动 pethospital.exe ...", file=sys.stderr)
    subprocess.Popen(
        [PET_HOSPITAL_EXE],
        cwd=PET_HOSPITAL_CWD,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        if _is_port_open("127.0.0.1", 8080):
            print(f"[pet-hospital MCP] pethospital.exe 已就绪。", file=sys.stderr)
            return
        time.sleep(0.2)
    print(f"[pet-hospital MCP] 警告: pethospital.exe 未能启动，请检查。", file=sys.stderr)

_ensure_pethospital()

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

class ListPetsInput(BaseModel):
    q: Optional[str] = Field(None, description="全文检索关键词，空格分词AND")
    name: Optional[str] = Field(None, description="宠物姓名")
    ownerName: Optional[str] = Field(None, description="主人姓名")
    ownerPhone: Optional[str] = Field(None, description="主人电话")
    species: Optional[str] = Field(None, description="种类")
    doctor: Optional[str] = Field(None, description="主治医生")
    disease: Optional[str] = Field(None, description="疾病")
    status: Optional[str] = Field(None, description="就诊状态")
    min_cost: Optional[float] = Field(None, description="最低总花费", alias="min")
    max_cost: Optional[float] = Field(None, description="最高总花费", alias="max")
    sort_by: Optional[str] = Field(None, description="排序字段")
    order: Optional[str] = Field(None, description="排序方向")
    page: Optional[int] = Field(1, ge=1, description="页码")
    page_size: Optional[int] = Field(20, ge=1, le=100, alias="pageSize", description="每页条数")

class PetCreateInput(BaseModel):
    name: str = Field(..., description="宠物姓名")
    species: str = Field(..., description="种类（犬/猫/兔等）")
    breed: Optional[str] = Field(None, description="品种")
    gender: Optional[str] = Field(None, description="性别（公/母）")
    ageMonths: Optional[int] = Field(None, description="月龄", alias="age_months")
    ownerName: Optional[str] = Field(None, description="主人姓名")
    ownerPhone: Optional[str] = Field(None, description="主人电话")
    doctor: Optional[str] = Field(None, description="主治医生")
    disease: Optional[str] = Field(None, description="疾病")
    status: Optional[str] = Field(None, description="就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访）")

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
async def fetch_pets(params: dict) -> ListPetsOutput:
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{PETHOSPITAL_API_URL}/api/v1/pets"
        query_params = {}
        for key, value in params.items():
            if value is not None and value != "":
                query_params[key] = str(value)
        resp = await client.get(url, params=query_params)
        resp.raise_for_status()
        json_data = resp.json()
        data = json_data["data"]
        return ListPetsOutput(
            items=[PetSummary(**item) for item in data["items"]],
            total=data["total"],
            page=data["page"],
            pageSize=data["pageSize"]
        )

async def create_pet_http(input_data: dict) -> CreatePetOutput:
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{PETHOSPITAL_API_URL}/api/v1/pets"
        body = {k: v for k, v in input_data.items() if v is not None}
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        json_data = resp.json()
        data = json_data["data"]
        return CreatePetOutput(**data)

# === MCP Tool Handlers ===
async def list_pets_handler(
    q: Optional[str] = None,
    name: Optional[str] = None,
    ownerName: Optional[str] = None,
    ownerPhone: Optional[str] = None,
    species: Optional[str] = None,
    doctor: Optional[str] = None,
    disease: Optional[str] = None,
    status: Optional[str] = None,
    min_cost: Optional[float] = None,
    max_cost: Optional[float] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = None,
    page: Optional[int] = 1,
    page_size: Optional[int] = 20,
) -> ListPetsOutput:
    params = {
        "q": q, "name": name, "ownerName": ownerName, "ownerPhone": ownerPhone,
        "species": species, "doctor": doctor, "disease": disease, "status": status,
        "min": min_cost, "max": max_cost,
        "sortBy": sort_by, "order": order,
        "page": page, "pageSize": page_size,
    }
    return await fetch_pets(params)

async def create_pet_handler(
    name: str,
    species: str,
    breed: Optional[str] = None,
    gender: Optional[str] = None,
    ageMonths: Optional[int] = None,
    ownerName: Optional[str] = None,
    ownerPhone: Optional[str] = None,
    doctor: Optional[str] = None,
    disease: Optional[str] = None,
    status: Optional[str] = None,
) -> CreatePetOutput:
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
    return await create_pet_http(input_data)

# === 服务器初始化 ===
mcp = FastMCP(
    "pet-hospital",
    instructions="宠物医院管理系统 MCP Server，提供宠物档案查询和新增服务。",
    host="0.0.0.0",
    port=MCP_PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
)

# 注册 list_pets 工具
@mcp.tool()
async def list_pets(
    q: Optional[str] = None,
    name: Optional[str] = None,
    ownerName: Optional[str] = None,
    ownerPhone: Optional[str] = None,
    species: Optional[str] = None,
    doctor: Optional[str] = None,
    disease: Optional[str] = None,
    status: Optional[str] = None,
    min_cost: Optional[float] = None,
    max_cost: Optional[float] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = None,
    page: Optional[int] = 1,
    page_size: Optional[int] = 20,
) -> ListPetsOutput:
    """查询宠物档案列表。支持按种类/医生/状态/疾病筛选，支持关键词搜索、分页和排序。"""
    return await list_pets_handler(
        q=q, name=name, ownerName=ownerName, ownerPhone=ownerPhone,
        species=species, doctor=doctor, disease=disease, status=status,
        min_cost=min_cost, max_cost=max_cost, sort_by=sort_by, order=order,
        page=page, page_size=page_size,
    )

# 注册 create_pet 工具
@mcp.tool()
async def create_pet(
    name: str,
    species: str,
    breed: Optional[str] = None,
    gender: Optional[str] = None,
    ageMonths: Optional[int] = None,
    ownerName: Optional[str] = None,
    ownerPhone: Optional[str] = None,
    doctor: Optional[str] = None,
    disease: Optional[str] = None,
    status: Optional[str] = None,
) -> CreatePetOutput:
    """添加新动物档案。返回创建的宠物档案信息。"""
    return await create_pet_handler(
        name=name, species=species, breed=breed, gender=gender,
        ageMonths=ageMonths, ownerName=ownerName, ownerPhone=ownerPhone,
        doctor=doctor, disease=disease, status=status,
    )

# === 启动 ===
if __name__ == "__main__":
    if MCP_TRANSPORT == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
