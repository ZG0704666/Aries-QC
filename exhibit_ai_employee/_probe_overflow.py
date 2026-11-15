import os, shutil, socket, subprocess, sys, tempfile, time, urllib.request, json
from playwright.sync_api import sync_playwright
ROOT = os.path.abspath(".")
PORT = 4214
BASE = "http://127.0.0.1:%d" % PORT
tmp = tempfile.mkdtemp(prefix="probe_")
db = os.path.join(tmp, "p.sqlite3"); shutil.copy("studio.sqlite3", db)
env = dict(os.environ); env.update({"STUDIO_DB": db, "STUDIO_AUDIO_DIR": os.path.join(ROOT, "audio"),
    "STUDIO_PORT": str(PORT), "STUDIO_HOST": "127.0.0.1"})
for k in ("STUDIO_ACCESS_TOKEN","ACCESS_TOKEN","STUDIO_ALLOW_NO_AUTH"): env.pop(k, None)
srv = subprocess.Popen([sys.executable, "studio_server.py"], cwd=ROOT, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/studio/health", timeout=2); break
        except Exception: time.sleep(0.4)
    with sync_playwright() as pw:
        b = pw.chromium.launch(); p = b.new_page(viewport={"width":1024,"height":900})
        p.goto(BASE + "/#live", wait_until="networkidle"); p.wait_for_timeout(800)
        out = p.evaluate("""() => {
          const de = document.documentElement;
          return [...document.querySelectorAll('#workspace-body *')]
            .filter(el => el.getBoundingClientRect().right > de.clientWidth + 1)
            .slice(0, 14)
            .map(el => ({tag: el.tagName, cls: el.className && el.className.toString().slice(0,40),
                         right: Math.round(el.getBoundingClientRect().right),
                         w: Math.round(el.getBoundingClientRect().width),
                         parent: el.parentElement.className.toString().slice(0,30),
                         ov: getComputedStyle(el.parentElement).overflowX}));
        }""")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        b.close()
finally:
    srv.terminate(); srv.wait(8); shutil.rmtree(tmp, ignore_errors=True)
