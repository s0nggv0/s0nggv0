from openai import OpenAI
import os

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


def main():
    if not os.path.exists(CONFIG_PATH):
        print("错误：config.ini 不存在")
        sys_exit()

    cfg = load_config(CONFIG_PATH)
    for field in ("base_rul", "mode_name", "key"):
        if field not in cfg:
            print("错误：缺少字段 " + field)
            sys_exit()

    print("你好，有什么问题")
    history = []
    while True:
        print()
        prompt = input("我：")
        history.append({"role": "user", "content": prompt})
        print("---")

        client = OpenAI(base_url=cfg["base_rul"], api_key=cfg["key"])
        stream = client.chat.completions.create(
            model=cfg["mode_name"],
            messages=history,
            stream=True,
        )
        reply = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                reply += delta
                print(delta, end="", flush=True)
        print()
        history.append({"role": "assistant", "content": reply})


def sys_exit():
    import sys

    sys.exit(1)


if __name__ == "__main__":
    main()
