import asyncio
import json

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TARGET = "http://127.0.0.1:8081/mcp"


def extract_text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
    return "\n".join(parts)


async def main() -> None:
    async with streamablehttp_client(TARGET) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("negotiated protocol:", init.protocolVersion)

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("tools:", names)
            assert "list_pets" in names, "list_pets missing"
            assert "create_pet" in names, "create_pet missing"

            listed = await session.call_tool("list_pets", {"page": 1, "pageSize": 3})
            summary = json.loads(extract_text(listed))
            print("list_pets total:", summary.get("total"), "->", summary.get("items", [{}])[0].get("id"))
            assert summary.get("total", 0) > 0, "list_pets returned empty"

            created = await session.call_tool(
                "create_pet",
                {
                    "name": "MCP测试喵2",
                    "species": "猫",
                    "ageMonths": 10,
                    "ownerName": "MCP测试员",
                    "ownerPhone": "13900000002",
                    "doctor": "李医生",
                    "disease": "体检",
                    "status": "待就诊",
                },
            )
            info = json.loads(extract_text(created))
            print("create_pet id:", info.get("id"), "name:", info.get("name"))
            assert info.get("id"), "create_pet returned no id"

            print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())