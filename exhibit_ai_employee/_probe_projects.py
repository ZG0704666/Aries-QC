"""只读+自建的接口探针：验证「空库即空库 / 新建 / 无资料不许生成 / 删除」这条链。"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:4182"


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main():
    status, data = call("GET", "/api/studio/projects")
    before = data.get("projects") or []
    print("现有项目 %d 个：%s" % (len(before), [(p["id"], p["name"], p["status"]) for p in before]))

    status, data = call("POST", "/api/studio/projects", {"name": ""})
    print("空名建项目 ->", status, data.get("error"))

    status, data = call("POST", "/api/studio/projects",
                        {"name": "探针项目", "audience": "内部测试", "language": "中文",
                         "brief": "只用来验证接口，跑完就删。"})
    print("建项目 ->", status)
    if status != 201:
        print("意外：", data)
        return
    pid = data["project"]["id"]
    p = data["project"]
    print("  id=%s status=%s version=%s demo=%s materials=%d exhibits=%d tests=%d review=%s"
          % (pid, p["status"], p["version"], p["demo"], len(p["materials"]), len(p["exhibits"]),
             len(p["tests"]), p["review"]))

    status, data = call("POST", "/api/studio/projects/%s/run" % pid, {})
    print("无资料直接生成 ->", status, data.get("error"))

    status, data = call("GET", "/api/studio/projects")
    ids = [x["id"] for x in (data.get("projects") or [])]
    print("新建后列表包含新项目：", pid in ids, "共 %d 个" % len(ids))

    status, data = call("POST", "/api/studio/projects/%s/delete" % pid, {})
    print("删除 ->", status, data)

    status, data = call("GET", "/api/studio/projects")
    after = data.get("projects") or []
    print("删除后剩 %d 个：%s" % (len(after), [(p["id"], p["name"]) for p in after]))
    print("列表已复原：", sorted(x["id"] for x in before) == sorted(x["id"] for x in after))

    status, data = call("POST", "/api/studio/projects/%s/delete" % pid, {})
    print("重复删除 ->", status, data.get("error"))


main()
