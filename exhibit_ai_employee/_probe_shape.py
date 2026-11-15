import json
import urllib.request

BASE = "http://127.0.0.1:4182"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


p = get("/api/studio/projects/7e1c974ff8")["project"]
print("TOP:", sorted(p.keys()))
for k in ("authorization", "voice", "review", "run_version", "brief"):
    print(k, "=", json.dumps(p.get(k), ensure_ascii=False)[:300])
print("chat[0]:", json.dumps(p["chat"][:2], ensure_ascii=False)[:500])
print("audio:", json.dumps(p["audio"], ensure_ascii=False)[:600])
print("exhibit keys:", sorted(p["exhibits"][0].keys()))
print("main:", json.dumps(p["exhibits"][0]["main"], ensure_ascii=False)[:200])
print("simplified:", json.dumps(p["exhibits"][0]["simplified"], ensure_ascii=False)[:200])
print("followups:", json.dumps(p["exhibits"][0]["followups"][:2], ensure_ascii=False)[:300])
print("fallback:", json.dumps(p["exhibits"][0]["fallback"][:2], ensure_ascii=False)[:300])
print("issues:", json.dumps(p["issues"], ensure_ascii=False)[:300])
print("tests[0]:", json.dumps(p["tests"][0], ensure_ascii=False)[:300])
print("sources[0] name/paras:", p["sources"][0]["name"], len(p["sources"][0]["paragraphs"]))
print("materials:", json.dumps(p["materials"], ensure_ascii=False)[:300])
q = get("/api/studio/projects/7e1c974ff8/events?after=0")
print("events:", len(q["events"]), "status:", q["status"])
for e in q["events"][-4:]:
    print(" ", e["kind"], json.dumps(e["detail"], ensure_ascii=False)[:180])
print("health:", json.dumps(get("/api/studio/health"), ensure_ascii=False)[:400])
print("projects:", json.dumps(get("/api/studio/projects"), ensure_ascii=False)[:600])
