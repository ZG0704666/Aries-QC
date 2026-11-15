"""一次性核对：交付包 zip 里是否已带实测时长（探针脚本，不进回归）。"""
import io
import json
import urllib.request
import zipfile
from pathlib import Path

PID = "7e1c974ff8"
URL = "http://127.0.0.1:4182/api/studio/projects/%s/export.zip" % PID
OUT = Path(__file__).with_name("_deliver_test") / "export_v2.zip"

raw = urllib.request.urlopen(URL, timeout=120).read()
OUT.parent.mkdir(exist_ok=True)
OUT.write_bytes(raw)
print("zip bytes", len(raw))

zf = zipfile.ZipFile(io.BytesIO(raw))
for info in zf.infolist():
    print("  %-34s %8d" % (info.filename, info.file_size))

manifest = json.loads(zf.read("交付清单.json").decode("utf-8"))
print("tests", manifest["tests"], "review", manifest["review"], "status", manifest["status"])
for item in manifest["files"]:
    print(
        "  file %-34s %8d  dur=%s  %s"
        % (
            item["path"],
            item["bytes"],
            item.get("duration_s"),
            item.get("engine"),
        )
    )

print("--- 交付稿前 10 行 ---")
for line in zf.read("交付稿.md").decode("utf-8").splitlines()[:10]:
    print(line)
