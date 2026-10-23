from openai import OpenAI
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.ini")


def load_config(path):
    cfg = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip()
    return cfg


def _decode(raw):
    """date 命令输出编码随终端代码页变化，依次尝试 UTF-8 / GBK"""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def getDate():
    try:
        result = subprocess.run(
            ["cmd", "/c", "date /t && time /t"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            out = _decode(result.stdout or b"")
            return " ".join(line.strip() for line in out.splitlines() if line.strip())
        err = _decode(result.stderr or b"") if result.stderr else ""
        return f"Error: {err}"
    except subprocess.TimeoutExpired:
        return "Error: date command timeout"
    except Exception as e:
        return f"Error: {e}"


def isLeapYear(year):
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return True
    return False


def sys_exit():
    sys.exit(1)


def main():
    if not os.path.exists(CONFIG_PATH):
        print("错误：config.ini 不存在")
        sys_exit()

    cfg = load_config(CONFIG_PATH)
    for field in ("base_url", "model_name", "key"):
        if field not in cfg:
            print("错误：缺少字段 " + field)
            sys_exit()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "getDate",
                "description": "获取当前电脑的日期和时间",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "isLeapYear",
                "description": "判断输入的年份是否是闰年",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "year": {
                            "type": "integer",
                            "description": "要判断的年份，例如 2024",
                        }
                    },
                    "required": ["year"],
                },
            },
        },
    ]

    print("你好，有什么问题（支持 function call: getDate, isLeapYear）")
    history = []
    while True:
        try:
            print()
            prompt = input("我：")
        except EOFError:
            break
        except KeyboardInterrupt:
            break
        history.append({"role": "user", "content": prompt})
        print("---")

        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["key"])

        while True:
            response = client.chat.completions.create(
                model=cfg["model_name"],
                messages=history,
                tools=tools,
                tool_choice="auto",
                stream=False,
            )

            message = response.choices[0].message

            if message.tool_calls:
                history.append(message.model_dump(exclude_none=True))
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "getDate":
                        tool_result = getDate()
                    elif tool_call.function.name == "isLeapYear":
                        args = json.loads(tool_call.function.arguments or "{}")
                        year = args.get("year")
                        if year is None:
                            tool_result = "Error: 缺少参数 year"
                        elif isLeapYear(int(year)):
                            tool_result = f"{year} 年是闰年"
                        else:
                            tool_result = f"{year} 年不是闰年"
                    else:
                        tool_result = f"Error: unknown tool {tool_call.function.name}"
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                    )
                    print(tool_result)
            else:
                reply = message.content or ""
                print(reply)
                history.append({"role": "assistant", "content": reply})
                break


if __name__ == "__main__":
    main()
