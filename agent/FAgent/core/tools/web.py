"""网络类工具：网页搜索、抓取正文并转换为 Markdown。"""

import json
import shutil
import subprocess
import urllib.error
import urllib.request

from ..config import ConfigError, load_search_api_key, setting, setting_int
from .registry import tool

DEFAULT_MAX_CHARS = 20_000
DEFAULT_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SEARCH_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"
SEARCH_TIMEOUT = 20
SEARCH_DEFAULT_TOP_K = 10
SEARCH_MAX_TOP_K = 50
SEARCH_SNIPPET_CHARS = 500


def _max_chars():
    return setting_int("web.max_chars", DEFAULT_MAX_CHARS)


def _fetch_timeout():
    return setting_int("web.timeout", DEFAULT_TIMEOUT)


def _connect_timeout(timeout):
    configured = setting_int("web.connect_timeout", 10)
    return min(configured, timeout) if configured > 0 else timeout


def _user_agent():
    return setting("web.user_agent", USER_AGENT)


def _search_endpoint():
    return setting("web.search_endpoint", SEARCH_ENDPOINT)


def _search_timeout():
    return setting_int("web.search_timeout", SEARCH_TIMEOUT)


def _search_top_k_default():
    return setting_int("web.search_default_top_k", SEARCH_DEFAULT_TOP_K)


def _search_top_k_max():
    return setting_int("web.search_max_top_k", SEARCH_MAX_TOP_K)


def _search_snippet_chars():
    return setting_int("web.search_snippet_chars", SEARCH_SNIPPET_CHARS)


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return None, "Error: 缺少参数 url"
    if not url.lower().startswith(("http://", "https://")):
        return None, "Error: 仅支持 http:// 或 https:// 开头的网页 URL"
    return url, None


def _fetch_html(url, timeout):
    curl = shutil.which("curl")
    if not curl:
        return None, "Error: 未找到 curl，请先安装 curl 并确保其在 PATH 中"

    args = [
        curl,
        "-sS",
        "-f",
        "-L",
        "--max-redirs",
        "10",
        "--connect-timeout",
        str(_connect_timeout(timeout)),
        "--max-time",
        str(timeout),
        "-A",
        _user_agent(),
        "--url",
        url,
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired:
        return None, f"Error: 访问网页超时（超过 {timeout} 秒）：{url}"
    except (OSError, ValueError) as e:
        return None, f"Error: 调用 curl 失败：{e}"

    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        return None, f"Error: 网页访问失败（curl 退出码 {result.returncode}）：{err or url}"
    if not result.stdout:
        return None, f"Error: 网页返回内容为空：{url}"
    return result.stdout, None


def _extract_markdown(html, url):
    try:
        import trafilatura
    except ImportError:
        return None, "Error: 缺少 trafilatura 依赖，请先执行 pip install trafilatura"

    try:
        markdown = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            include_links=True,
            include_formatting=True,
            output_format="markdown",
        )
    except Exception as e:
        return None, f"Error: HTML 解析失败：{e}"
    if not markdown or not markdown.strip():
        return (
            None,
            f"Error: 无法从该网页提取正文，页面可能由脚本动态渲染或内容过少：{url}",
        )
    return markdown.strip(), None


def _search_request(query, top_k, api_key):
    """调用千帆百度搜索 API，返回 (references, error)"""
    payload = {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2",
        "edition": "standard",
        "resource_type_filter": [{"type": "web", "top_k": top_k}],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _search_endpoint(),
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    timeout = _search_timeout()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as e:
        return None, _search_http_error(e)
    except urllib.error.URLError as e:
        return None, f"Error: 无法连接搜索服务：{e.reason}"
    except TimeoutError:
        return None, f"Error: 搜索请求超时（超过 {timeout} 秒）"
    except OSError as e:
        return None, f"Error: 搜索请求失败：{e}"

    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"Error: 搜索服务返回了无法解析的响应：{e}"

    if not isinstance(result, dict):
        return None, "Error: 搜索服务返回了异常格式的响应"

    code = result.get("code")
    if code not in (None, 0, "0"):
        message = result.get("message") or result.get("msg") or "未知错误"
        request_id = result.get("request_id") or result.get("requestId") or ""
        suffix = f"（request_id: {request_id}）" if request_id else ""
        return None, f"Error: 百度搜索 API 返回错误（code={code}）：{message}{suffix}"

    references = result.get("references")
    if references is None:
        message = result.get("message") or "响应中缺少 references 字段"
        return None, f"Error: 搜索服务未返回结果：{message}"
    if not isinstance(references, list):
        return None, "Error: 搜索服务返回的 references 字段格式异常"
    return references, None


def _search_http_error(error):
    """把 HTTP 错误响应中的 API 错误信息提取出来"""
    detail = ""
    try:
        raw = error.read()
        parsed = json.loads(raw.decode("utf-8"))
        if isinstance(parsed, dict):
            detail = parsed.get("message") or parsed.get("msg") or ""
            code = parsed.get("code")
            if code not in (None, 0, "0"):
                detail = f"code={code}：{detail}" if detail else f"code={code}"
    except Exception:
        detail = ""
    if not detail:
        detail = error.reason
    return f"Error: 搜索请求失败（HTTP {error.code}）：{detail}"


def _format_search_results(query, references):
    """把搜索结果整理为摘要 + 参考来源，便于模型阅读与引用"""
    if not references:
        return f"未找到与「{query}」相关的网页结果。"

    blocks = []
    sources = []
    snippet_chars = _search_snippet_chars()
    for index, item in enumerate(references, start=1):
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("web_anchor") or "无标题").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or "").strip()
        date = (item.get("date") or "").strip()

        if snippet_chars > 0 and len(content) > snippet_chars:
            content = content[:snippet_chars] + "..."

        lines = [f"## {index}. {title}"]
        if content:
            lines.append(f"摘要：{content}")
        if date:
            lines.append(f"发布时间：{date}")
        if url:
            lines.append(f"来源：{url}")
        blocks.append("\n".join(lines))
        sources.append(f"{index}. {title}\n   {url or '（无链接）'}")

    if not blocks:
        return f"未找到与「{query}」相关的网页结果。"

    header = f"搜索问题：{query}\n共返回 {len(blocks)} 条网页结果。"
    return (
        header
        + "\n\n"
        + "\n\n".join(blocks)
        + "\n\n## 参考来源\n"
        + "\n".join(sources)
    )


@tool(
    "searchWeb",
    "使用百度搜索获取互联网上的实时信息。传入搜索关键词或问题，"
    "返回搜索结果摘要以及参考来源的标题和 URL，适合查询最新资讯、"
    "事实性信息或需要联网核实的内容",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或需要解答的问题",
            },
            "top_k": {
                "type": "integer",
                "description": "返回的网页结果数量，默认值与上限由 config.ini 的 [web] 小节配置",
            },
        },
        "required": ["query"],
    },
)
def search_web(query, top_k=None):
    query = (query or "").strip()
    if not query:
        return "Error: 缺少参数 query"

    default_top_k = _search_top_k_default()
    max_top_k = _search_top_k_max()
    if top_k is None:
        top_k = default_top_k
    else:
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = default_top_k
    top_k = max(1, min(top_k, max_top_k))

    try:
        api_key = load_search_api_key()
    except ConfigError as e:
        return f"Error: {e}"
    except OSError as e:
        return f"Error: 读取搜索配置失败：{e}"

    references, error = _search_request(query, top_k, api_key)
    if error:
        return error
    return _format_search_results(query, references)


@tool(
    "fetchWeb",
    "获取指定网页的主要内容，自动提取正文并转换为 Markdown，"
    "保留标题、段落、列表、表格与链接，去除导航栏、广告、页脚等无关内容",
    {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要抓取的网页 URL，必须以 http:// 或 https:// 开头",
            },
            "max_chars": {
                "type": "integer",
                "description": "最多返回的字符数，默认由 config.ini 的 web.max_chars 配置",
            },
        },
        "required": ["url"],
    },
)
def fetch_web(url, max_chars=None):
    url, error = _normalize_url(url)
    if error:
        return error

    limit = _max_chars()
    if max_chars is None:
        max_chars = limit
    else:
        try:
            max_chars = int(max_chars)
        except (TypeError, ValueError):
            max_chars = limit
    if max_chars <= 0:
        max_chars = limit

    html, error = _fetch_html(url, _fetch_timeout())
    if error:
        return error

    markdown, error = _extract_markdown(html, url)
    if error:
        return error

    total = len(markdown)
    if total > max_chars:
        markdown = markdown[:max_chars] + f"\n\n...（内容已截断，正文共 {total} 字符）"
    return f"URL: {url}\n\n{markdown}"
