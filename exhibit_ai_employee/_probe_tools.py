"""探测：DeepSeek 的 /chat/completions 是否支持原生 function calling（tools），
以及带 tools 时能否正常返回 tool_calls。只发一次很小的请求。"""
import json
import os
import urllib.request

BASE = os.environ.get("AI_BASE_URL") or "https://api.deepseek.com/v1"
KEY = os.environ.get("DEEPSEEK_API_KEY") or ""
MODEL = os.environ.get("AI_MODEL") or "deepseek-chat"


def load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
KEY = os.environ.get("DEEPSEEK_API_KEY", "")

TOOLS = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "联网搜索，返回若干条网页结果（标题 / 链接 / 摘要）。需要核实事实或找新信息时调用。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索词"}},
            "required": ["query"],
        },
    },
}]


def post(payload):
    req = urllib.request.Request(
        BASE.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


print("base:", BASE, "| model:", MODEL, "| key:", bool(KEY))

messages = [{"role": "user", "content": "帮我查一下「光的折射」在日常生活里的例子，要求联网搜索后回答。"}]
payload = {"model": MODEL, "messages": messages, "tools": TOOLS, "tool_choice": "auto",
           "temperature": 0.2, "max_tokens": 400}
try:
    data = post(payload)
    msg = data["choices"][0]["message"]
    print("finish_reason:", data["choices"][0].get("finish_reason"))
    print("content:", (msg.get("content") or "")[:200])
    print("tool_calls:", json.dumps(msg.get("tool_calls"), ensure_ascii=False)[:600])
    print("usage:", data.get("usage"))
    if msg.get("tool_calls"):
        print("\n--- 回填一次工具结果，看模型能否收尾 ---")
        call = msg["tool_calls"][0]
        messages.append(msg)
        messages.append({"role": "tool", "tool_call_id": call["id"],
                         "content": json.dumps([{"title": "折射 - 科普中国", "url": "https://example.org/1",
                                                 "snippet": "光从空气斜射入水中时传播方向发生偏折，这就是折射。"}],
                                               ensure_ascii=False)})
        data2 = post({"model": MODEL, "messages": messages, "tools": TOOLS, "temperature": 0.2, "max_tokens": 300})
        msg2 = data2["choices"][0]["message"]
        print("第二轮 content:", (msg2.get("content") or "")[:300])
        print("第二轮 tool_calls:", json.dumps(msg2.get("tool_calls"), ensure_ascii=False)[:300])
except Exception as exc:
    body = getattr(exc, "read", lambda: b"")()
    print("失败 %s: %s" % (type(exc).__name__, str(exc)[:200]))
    print("body:", body.decode("utf-8", "replace")[:600])
