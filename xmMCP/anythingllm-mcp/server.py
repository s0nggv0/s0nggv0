import logging
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from anythingllm import AnythingLLMClient, AnythingLLMError
from config import load_config

logger = logging.getLogger(__name__)

config = load_config()

client = AnythingLLMClient(
    base_url=config.anythingllm_url,
    api_key=config.anythingllm_api_key,
    session_id=config.session_id,
    workspace_slug=config.workspace_slug,
)

mcp = MCPServer("anythingllm-mcp", log_level=config.log_level)


@mcp.tool(
    title="Ask the AnythingLLM workspace",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def workspace_chat(
    message: Annotated[str, Field(description="The question to ask.")],
    mode: Literal["chat", "query", "automatic"] = "chat",
) -> str:
    """Ask a question and answer it from the single AnythingLLM workspace: the reply is grounded in the documents and knowledge stored in that workspace."""
    try:
        return client.chat(message, mode=mode)
    except AnythingLLMError as exc:
        raise RuntimeError(str(exc)) from exc


@mcp.tool(
    title="Count files in the AnythingLLM workspace",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def workspace_file_count(
    include_names: Annotated[
        bool,
        Field(description="When true, also list every file name stored in the workspace."),
    ] = False,
) -> str:
    """Return how many files (documents) are stored in the AnythingLLM workspace, optionally listing their names."""
    try:
        documents = client.get_workspace_documents()
    except AnythingLLMError as exc:
        raise RuntimeError(str(exc)) from exc
    total = len(documents)
    if not include_names:
        return f"The workspace contains {total} file(s)."
    listing = "\n".join(f"- {client.document_title(doc)}" for doc in documents)
    return f"The workspace contains {total} file(s):\n{listing}"


if __name__ == "__main__":
    try:
        slug = client.resolve_workspace_slug()
        logger.info("Using AnythingLLM workspace: %s", slug)
    except Exception as exc:
        logger.warning("Workspace resolution failed at startup: %s", exc)

    mcp.run(
        transport="streamable-http",
        host=config.mcp_host,
        port=config.mcp_port,
        streamable_http_path=config.mcp_path,
        json_response=True,
        stateless_http=True,
    )