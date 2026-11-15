"""探测本机可用的联网通道：搜索引擎与网页抓取。只打印结果，不改任何东西。"""
import json
import re
import sys
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch(url, timeout=12, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return r.status, r.headers.get("Content-Type", ""), raw


def probe(name, url, needle=None, headers=None):
    try:
        status, ctype, raw = fetch(url, headers=headers)
        text = raw.decode("utf-8", "replace")
        hit = "" if needle is None else ("命中 %s" % needle if needle in text else "未命中 %s" % needle)
        print("%-22s %s %6dB %-28s %s" % (name, status, len(raw), ctype[:28], hit))
        return text
    except Exception as exc:
        print("%-22s 失败 %s: %s" % (name, type(exc).__name__, str(exc)[:90]))
        return None


def ddg_html(query):
    body = urllib.parse.urlencode({"q": query, "kl": "cn-zh"}).encode()
    req = urllib.request.Request("https://html.duckduckgo.com/html/", data=body,
                                 headers={"User-Agent": UA,
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        text = r.read().decode("utf-8", "replace")
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.S)
    out = []
    for href, title in links[:5]:
        href = urllib.parse.unquote(re.sub(r"^//duckduckgo\.com/l/\?uddg=", "", href))
        out.append((re.sub(r"<[^>]+>", "", title).strip(), href))
    return out


print("=== 直连可达性 ===")
probe("duckduckgo html", "https://html.duckduckgo.com/html/?q=test")
probe("ddg lite", "https://lite.duckduckgo.com/lite/?q=test")
probe("bing cn", "https://cn.bing.com/search?q=test")
probe("bing www", "https://www.bing.com/search?q=test")
probe("baidu", "https://www.baidu.com/s?wd=test")
probe("searx be", "https://searx.be/search?q=test&format=json")
probe("wikipedia api", "https://zh.wikipedia.org/api/rest_v1/page/summary/%E5%85%89")
probe("example.com", "https://example.com/")
probe("mojeek", "https://www.mojeek.com/search?q=test")

print("\n=== 结果抓取（关键字命中判断） ===")
text = ddg_html("光的折射 原理")
print("ddg 结果条数:", len(text))
for title, href in text[:5]:
    print("  ·", title[:40], "→", href[:80])

probe("中国科普博览", "https://www.kepuchina.cn/", "科普")
