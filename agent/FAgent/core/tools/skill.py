"""技能类工具：createSkill 创建新技能，loadSkill 按需加载技能全文或其附件文件。"""

from ..skills import (
    compose_skill_document,
    default_skills_dir,
    discover_skills,
    find_skill,
    load_skill_text,
    normalize_skill_name,
    read_text,
    resolve_skill_file,
)
from .registry import tool


@tool(
    "createSkill",
    "根据用户要求创建新技能：在项目技能目录 .agents/skills/ 下生成以 name 命名的"
    "英文子目录，并写入符合 Agent Skills 规范的 SKILL.md（含 YAML frontmatter、"
    "name、description 与正文）。name 会统一规范为小写字母、数字和连字符格式；"
    "目标技能已存在时返回提示且不覆盖。references/、scripts/ 等辅助文件请继续"
    "使用文件类工具创建。",
    {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "技能名称，将规范为小写字母、数字和连字符格式，例如 weekly-report",
            },
            "skillContext": {
                "type": "string",
                "description": (
                    "需要写入 SKILL.md 的完整内容，可包含 frontmatter 与正文；"
                    "缺少 frontmatter 时会自动补全 name 与 description"
                ),
            },
        },
        "required": ["name", "skillContext"],
    },
)
def create_skill(name, skillContext):
    skill_name, error = normalize_skill_name(name)
    if error:
        return error

    document, error = compose_skill_document(skill_name, skillContext)
    if error:
        return error

    directory = default_skills_dir() / skill_name
    entrypoint = directory / "SKILL.md"
    existing = find_skill(skill_name)
    if existing is not None or directory.exists():
        location = existing.directory if existing is not None else directory
        return f"Error: 技能 {skill_name} 已存在（{location}），未覆盖原有内容"

    try:
        directory.mkdir(parents=True, exist_ok=False)
        entrypoint.write_text(document, encoding="utf-8")
    except OSError as e:
        return f"Error: 创建技能失败：{e}"

    return (
        f"已创建技能 {skill_name}：{entrypoint}\n"
        "如需 references/、scripts/ 等辅助文件，请继续调用 createFile、"
        "createDirectory 等文件工具。新技能将在下次启动 FAgent 时被识别。"
    )


@tool(
    "loadSkill",
    "加载已安装技能的完整说明或其附件文件。仅传 name 时返回该技能 SKILL.md 全文；"
    "同时传 filename 时只读取对应的附件文件，不重复返回 SKILL.md。filename 支持"
    "相对技能目录的路径、项目相对路径与绝对路径；仅提供文件名时在技能目录内递归搜索，"
    "存在多个同名文件时会返回候选路径。读取范围限制在该技能目录内部。",
    {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "技能名（SKILL.md frontmatter 的 name）或技能目录名，例如 humanizer",
            },
            "filename": {
                "type": "string",
                "description": "可选，要加载的技能附件文件路径或文件名，例如 references/banned-words.md",
            },
        },
        "required": ["name"],
    },
)
def load_skill(name, filename=None):
    skill = find_skill(name)
    if skill is None:
        available = "、".join(s.name for s in discover_skills()) or "无"
        return f"Error: 未找到技能 {name}；可用技能：{available}"

    if filename is None or not str(filename).strip():
        header = f"[Skill: {skill.name} | 技能目录: {skill.directory}]\n\n"
        return header + load_skill_text(skill)

    path, error = resolve_skill_file(skill, filename)
    if error:
        return error
    try:
        text = read_text(path)
    except OSError as e:
        return f"Error: 读取文件失败：{e}"
    return f"[Skill {skill.name} 附件文件: {path}]\n\n{text}"
