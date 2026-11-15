"""联网查证：搜索 + 抓正文。

本机实测结论（2026-11-15，见 _probe_web.py / _probe_web2.py）：
- cn.bing.com / www.bing.com 的 HTML 可解析出标题、链接、摘要 → 作为搜索主通道；
- DuckDuckGo HTML、lite、searx.be 全部超时；百度只回 1.5KB 空壳；mojeek 对脚本返回 403；
- 正文抓取因站点而异：科普中国这类静态站可读，百度百科只回 4 个字（前端渲染），
  维基百科 SSL 握手直接超时，部分站点还会因为本机证书链不全报 CERTIFICATE_VERIFY_FAILED。

所以这里的策略是：**能搜到就列出来，抓不到正文就如实说抓不到**，
绝不拿摘要冒充正文，也绝不编造一条搜索结果。搜索结果里的摘要本来就是
搜索引擎给的原文摘录，用它做佐证是诚实的；但会标注 `text_source="snippet"`。
"""
import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
TIMEOUT = float(os.environ.get("WEB_TIMEOUT", "15"))
MAX_BYTES = int(os.environ.get("WEB_MAX_BYTES", str(2 * 1024 * 1024)))
MAX_TEXT = int(os.environ.get("WEB_MAX_TEXT", "6000"))
SEARCH_COUNT = int(os.environ.get("WEB_SEARCH_COUNT", "6"))

_STRICT = ssl.create_default_context()
_RELAXED = ssl.create_default_context()
_RELAXED.check_hostname = False
_RELAXED.verify_mode = ssl.CERT_NONE


class WebError(Exception):
    """联网失败。message 直接展示给人看，必须说清发生了什么。"""


# ---------------------------------------------------------------- 基础工具

def _blocked_host(host):
    """只允许访问公网地址：挡住本机、内网、链路本地等目标（避免被当成内网探针）。"""
    if not host:
        return "地址里没有主机名"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None  # 解析不了就交给真正的请求去报错，错误信息更具体
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "拒绝访问内网地址 %s" % addr
    return None


def _check_url(url):
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise WebError("只支持 http/https 链接，收到的是「%s」" % (parsed.scheme or url[:20]))
    reason = _blocked_host(parsed.hostname)
    if reason:
        raise WebError(reason)
    return parsed


def _open(url, timeout=None):
    """先按默认校验，证书链不全时退一步重试，并把「未校验」这个事实带出来。"""
    timeout = timeout or TIMEOUT
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_STRICT), False
    except ssl.SSLCertVerificationError:
        req = urllib.request.Request(url, headers=HEADERS)
        return urllib.request.urlopen(req, timeout=timeout, context=_RELAXED), True


def strip_html(html):
    if not html:
        return ""
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?is)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def page_title(html):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    return unescape(re.sub(r"\s+", " ", m.group(1)).strip()) if m else ""


# ---------------------------------------------------------------- 搜索

def _bing(query, count):
    url = "https://cn.bing.com/search?q=%s&setlang=zh-CN&count=%d" % (
        urllib.parse.quote(query), max(count, 4))
    resp, unverified = _open(url)
    try:
        raw = resp.read(MAX_BYTES)
    finally:
        resp.close()
    html = raw.decode("utf-8", "replace")
    out = []
    for block in re.findall(r'(?is)<li class="b_algo".*?</li>', html):
        m = re.search(r'(?is)<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not m:
            continue
        href = unescape(m.group(1))
        if href.startswith("/"):
            href = "https://cn.bing.com" + href
        if not href.startswith("http"):
            continue
        title = strip_html(m.group(2)) or page_title(block)
        snippet = ""
        sm = re.search(r'(?is)<p[^>]*>(.*?)</p>', block)
        if sm:
            snippet = strip_html(sm.group(1))
        if not snippet:
            sm = re.search(r'(?is)class="b_caption".*?<span[^>]*>(.*?)</span>', block)
            if sm:
                snippet = strip_html(sm.group(1))
        out.append({"title": title[:160], "url": href, "snippet": snippet[:400],
                    "text_source": "snippet"})
    return out, unverified


STOPWORDS = (
    "为什么", "为啥", "怎么", "怎样", "如何", "请问", "是什么", "有哪些", "什么", "多少",
    "可以", "需要", "我们", "他们", "这个", "那个", "一个", "一下", "为什么", "会",
)
# 这些站点的页面多半是「查字/查词」结果，当问题不是问字词时价值很低
DICT_TITLE_HINTS = ("汉典", "新华字典", "汉语国学", "词典", "拼音", "笔顺", "怎么读", "的意思")


def _tokens(text):
    """把问题切成可比对的检索单元：中文用二元组，英文按词。"""
    text = (text or "").lower()
    tokens = set()
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
        for i in range(len(chunk) - 1):
            tokens.add(chunk[i:i + 2])
        if len(chunk) == 1:
            tokens.add(chunk)
    for word in re.findall(r"[a-z][a-z0-9\-]{1,}", text):
        tokens.add(word)
    return tokens


def _score(question_tokens, item):
    title = (item.get("title") or "").lower()
    snippet = (item.get("snippet") or "").lower()
    score = 0
    for tok in question_tokens:
        if tok in title:
            score += 3
        elif tok in snippet:
            score += 1
    return score


def _variants(query):
    """一条问题给出几种说法。Bing 对长句中文容易只认第一个词，短关键词更稳。"""
    out = []
    raw = query.strip()

    def push(text):
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if text and text not in out:
            out.append(text)

    push(raw)
    stripped = raw
    for word in STOPWORDS:
        stripped = stripped.replace(word, " ")
    stripped = stripped.replace("的", " ")
    stripped = re.sub(r"[，。？！、,.?!；;:：]", " ", stripped)
    push(stripped)
    words = [w for w in stripped.split() if w]
    if len(words) > 2:
        push(" ".join(words[:2]))
    if len(words) > 1:
        push(words[0])
    return out[:3]


def search(query, count=None):
    """搜一次，必要时换几种说法重搜，按与问题的贴合度排序。

    返回 {query, engine, queries_tried, results:[{title,url,snippet,text_source}],
          cert_unverified, weak_match}。
    """
    query = (query or "").strip()
    if not query:
        raise WebError("搜索词是空的")
    if len(query) > 200:
        query = query[:200]
    count = count or SEARCH_COUNT
    q_tokens = _tokens(query)

    collected, unverified, tried, errors = [], False, [], []
    for variant in _variants(query):
        try:
            results, unv = _bing(variant, count)
        except (socket.timeout, TimeoutError):
            errors.append("搜索引擎 %d 秒没有响应" % int(TIMEOUT))
            continue
        except urllib.error.HTTPError as exc:
            errors.append("搜索引擎返回 %d" % exc.code)
            continue
        except urllib.error.URLError as exc:
            errors.append("搜索引擎连不上（%s）" % str(getattr(exc, "reason", exc))[:60])
            continue
        tried.append(variant)
        unverified = unverified or unv
        for item in results:
            item["via"] = variant
            collected.append(item)
        # 已经找到贴合问题标题的结果就不再多问几次
        if any(_score(q_tokens, it) >= 6 for it in results):
            break

    if not collected:
        raise WebError(errors[0] if errors else "搜索引擎没有返回结果，换个说法再试一次。")

    seen, uniq = set(), []
    for item in collected:
        key = item["url"].split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)

    for item in uniq:
        item["score"] = _score(q_tokens, item)
    uniq.sort(key=lambda it: it["score"], reverse=True)

    weak = not uniq or uniq[0]["score"] == 0
    # 问题不是在问字词，就别把「查字」页面排在最前面
    if "字的" not in query and "汉字" not in query and "拼音" not in query:
        uniq.sort(key=lambda it: (any(h in it["title"] for h in DICT_TITLE_HINTS),
                                  -it["score"]))
    return {"query": query, "engine": "bing", "queries_tried": tried,
            "count": len(uniq[:count]), "results": uniq[:count],
            "cert_unverified": unverified, "weak_match": weak}


# ---------------------------------------------------------------- 抓正文

def fetch(url, max_text=None):
    """抓一页正文。抓不到就说抓不到，不拿摘要顶替。"""
    _check_url(url)
    max_text = max_text or MAX_TEXT
    try:
        resp, unverified = _open(url)
        try:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read(MAX_BYTES)
        finally:
            resp.close()
    except urllib.error.HTTPError as exc:
        raise WebError("对方返回 %d（%s），这页读不了。" % (exc.code, exc.reason))
    except ssl.SSLError as exc:
        raise WebError("和这个站点建立加密连接失败（%s）。" % str(exc)[:60])
    except (socket.timeout, TimeoutError):
        raise WebError("打开这页超时（%d 秒）。" % int(TIMEOUT))
    except urllib.error.URLError as exc:
        raise WebError("打不开这页：%s" % str(exc.reason)[:90])

    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    if m:
        charset = m.group(1)
    else:
        m = re.search(rb'(?i)charset=["\']?([\w-]+)', raw[:2048])
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    try:
        html = raw.decode(charset, "replace")
    except LookupError:
        html = raw.decode("utf-8", "replace")

    text = strip_html(html)
    title = page_title(html)
    note = ""
    if len(text) < 200:
        note = ("这页只取到 %d 个字符的正文——多数是前端脚本渲染的页面，"
                "服务端拿不到内容。可以换一个来源。" % len(text))
    return {"url": url, "title": title[:160], "chars": len(text),
            "text": text[:max_text], "truncated": len(text) > max_text,
            "cert_unverified": unverified, "note": note,
            "content_type": ctype[:60]}


# ---------------------------------------------------------------- 给模型用的工具

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": ("联网搜索。需要核实一个事实、找例子、找资料时用。"
                            "返回若干条网页的标题、链接和摘要。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索词，像人在浏览器里输入的那样"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": ("打开一个网页并读取正文。想看清某条结果的原文时用；"
                            "有的站点只返回很少内容，那就是真的取不到。"),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "以 http/https 开头的完整链接"}},
                "required": ["url"],
            },
        },
    },
]


def run_tool(name, args):
    """执行模型要的工具，返回 (给模型看的文本, 结构化结果或 None)。失败也返回文本，让模型知道并换路子。"""
    try:
        if name == "web_search":
            data = search(args.get("query", ""))
            lines = ["搜索「%s」得到 %d 条结果：" % (data["query"], len(data["results"]))]
            for i, item in enumerate(data["results"], 1):
                lines.append("%d. %s\n   %s\n   %s" % (i, item["title"], item["url"],
                                                       item["snippet"] or "（这条没有摘要）"))
            if data["cert_unverified"]:
                lines.append("（提示：与搜索引擎的证书校验未通过，但内容已取到。）")
            return "\n".join(lines), data
        if name == "fetch_url":
            data = fetch(args.get("url", ""))
            body = data["text"] or "（正文是空的）"
            head = "《%s》%s，正文 %d 字%s" % (
                data["title"] or "无标题", data["url"], data["chars"],
                "（已截断）" if data["truncated"] else "")
            text = head + "\n" + body
            if data["note"]:
                text += "\n（%s）" % data["note"]
            return text, data
        return "没有这个工具：%s" % name, None
    except WebError as exc:
        return "刚才没成功：%s" % exc, None
    except Exception as exc:  # 兜底：绝不让工具把整轮对话炸掉
        return "刚才没成功：%s（%s）" % (str(exc)[:120], type(exc).__name__), None


def status():
    """给健康检查用：报告联网能力是否配置齐全，不做真实请求。"""
    return {"engine": "bing", "timeout": TIMEOUT, "max_text": MAX_TEXT,
            "tools": [t["function"]["name"] for t in TOOL_SPECS]}


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "光的折射 生活例子"
    print(json.dumps(status(), ensure_ascii=False))
    data = search(q)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:1500])
    if data["results"]:
        url = data["results"][0]["url"]
        try:
            page = fetch(url)
            print("\n抓正文:", url, "→", page["chars"], "字")
            print(page["text"][:300].replace("\n", " "))
        except WebError as exc:
            print("\n抓正文失败:", exc)
