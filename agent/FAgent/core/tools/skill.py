"""技能类工具：loadSkill 按需加载技能全文或其附件文件。"""

from ..skills import (
    discover_skills,
    find_skill,
    load_skill_text,
    read_text,
    resolve_skill_file,
)
from .registry import tool


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
