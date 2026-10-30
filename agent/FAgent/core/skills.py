"""技能（Skill）发现与加载。

遵循 Agent Skills 规范：以程序启动时的工作目录为项目根，
扫描 ``<项目根>/.agents/skills/<技能目录>/SKILL.md``，
文件以 YAML frontmatter 开头，至少包含 ``name`` 与 ``description``。
初始化阶段只读取这两个字段，技能正文在模型调用 loadSkill 时才进入上下文。
"""

from dataclasses import dataclass
from pathlib import Path

FRONTMATTER_DELIMITER = "---"

# 程序启动时的工作目录，作为项目根（不是 Python 安装目录，也不是代码存放目录）
PROJECT_ROOT = Path.cwd()


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    directory: Path

    @property
    def entrypoint(self):
        return self.directory / "SKILL.md"


def project_root():
    """项目根目录：程序启动时的工作目录。"""
    return PROJECT_ROOT


def default_skills_dir():
    """技能目录位于项目根下的 .agents/skills/。"""
    return PROJECT_ROOT / ".agents" / "skills"


def _read_frontmatter(text):
    """拆分 frontmatter 与正文，解析单行 key: value 及 key: |（或 key: >）多行块标量。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return {}, text

    meta = {}
    i = 1
    n = len(lines)
    block_indicators = {"|", "|-", "|+", ">", ">-", ">+"}

    while i < n:
        line = lines[i]
        if line.strip() == FRONTMATTER_DELIMITER:
            i += 1
            break

        stripped = line.strip()
        # 跳过空行、列表项与不含冒号的行
        if not stripped or stripped.startswith("-") or ":" not in line:
            i += 1
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'").strip()

        if value in block_indicators:
            # 块标量：收集后续缩进行作为该键的多行值
            block = []
            i += 1
            while i < n:
                bline = lines[i]
                if bline.strip() == FRONTMATTER_DELIMITER:
                    break
                if bline.strip() == "":
                    block.append("")
                    i += 1
                    continue
                # 无缩进且含冒号的下一键行视为块结束
                if not bline[0].isspace() and ":" in bline:
                    break
                block.append(bline.strip())
                i += 1
            meta[key] = "\n".join(block).strip()
            continue

        if value:
            meta[key] = value
        i += 1

    return meta, "\n".join(lines[i:]).lstrip("\n")


def discover_skills(directory=None):
    """扫描技能目录，按目录名排序返回可用技能（仅解析 name 与 description）。"""
    root = Path(directory) if directory else default_skills_dir()
    if not root.is_dir():
        return []

    skills = []
    seen = set()
    for entry in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not entry.is_dir():
            continue
        md_path = entry / "SKILL.md"
        if not md_path.is_file():
            continue
        try:
            text = md_path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        meta, _ = _read_frontmatter(text)
        name = meta.get("name") or entry.name
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        description = (
            meta.get("description")
            or meta.get("description_zh")
            or meta.get("description_en")
            or ""
        )
        skills.append(
            Skill(name=name, description=description, directory=entry.resolve())
        )
    return skills


def find_skill(name):
    """按技能名（frontmatter 的 name）或技能目录名查找技能。"""
    query = str(name).strip().lstrip("@").lower()
    if not query:
        return None
    for skill in discover_skills():
        if query in (skill.name.lower(), skill.directory.name.lower()):
            return skill
    return None


def read_text(path):
    """读取文本文件，自动识别 UTF-8 与 GBK 编码。"""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="gbk")


def load_skill_text(skill):
    """读取 SKILL.md 全文（含 frontmatter）。"""
    return read_text(skill.entrypoint)


def _is_inside(root, path):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_skill_file(skill, filename):
    """解析技能附件文件路径，返回 (绝对路径, 错误信息)，二者必有一为 None。

    优先精确路径匹配：绝对路径 > 相对技能目录 > 相对项目根；
    精确匹配未命中时按文件名在技能目录内递归搜索，命中多个则返回候选路径。
    读取范围限制在指定技能的目录内部，防止路径解析越界。
    """
    raw = str(filename).strip().strip('"').strip("'")
    if not raw:
        return None, "Error: filename 不能为空"

    supplied = Path(raw)
    candidates = []
    if supplied.is_absolute():
        candidates.append(supplied)
    else:
        normalized = Path(raw.replace("\\", "/"))
        candidates.append(skill.directory / normalized)
        candidates.append(PROJECT_ROOT / normalized)

    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_file():
            continue
        if not _is_inside(skill.directory, resolved):
            return None, f"Error: 拒绝读取技能目录之外的文件：{resolved}"
        return resolved, None

    target = supplied.name
    matches = sorted(
        path.resolve()
        for path in skill.directory.rglob("*")
        if path.is_file() and path.name == target
    )
    if not matches:
        return None, f"Error: 技能 {skill.name} 中未找到文件 {raw}"
    if len(matches) > 1:
        listed = "\n".join(f"- {path}" for path in matches)
        return None, (
            f"技能 {skill.name} 中存在 {len(matches)} 个同名文件 {target}，"
            f"请从以下候选中选择一个完整路径再次调用：\n{listed}"
        )
    return matches[0], None


def build_skills_prompt(skills):
    """生成注入系统提示的技能清单与 loadSkill 调用约定。"""
    if not skills:
        return ""

    lines = ["You have access to the following skills:"]
    for skill in skills:
        description = skill.description or "No description"
        lines.append(f"- '{skill.name}': {description}")
    lines.append(
        "Use the 'loadSkill' tool to load the full instructions of a skill "
        "when needed. You can also load additional files referenced by a "
        "skill by passing its filename."
    )
    return "\n".join(lines)
