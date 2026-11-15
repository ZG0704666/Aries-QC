"""为走查脚本生成一个真实形状的夹具项目（临时库 + 临时音频目录）。

不依赖仓库里任何现存项目，也不碰真实 studio.sqlite3：这里现场用 ffmpeg
合成三段静音 MP3，再按真实项目的 JSON 形状写入 3 个展项、事实、自测结果
与音频登记，最后由 studio_server 自己的 content_tests() 判一遍。

跑法：python _fixture.py <db.sqlite3> <audio_dir> [project_id]
输出：一行 JSON，含项目 id / 名称 / 展项标题 / 音频文件名。
"""
import hashlib
import json
import os
import subprocess
import sys

MATERIALS = [
    {"name": "夹具资料-光学.txt", "text": "\n".join([
        "光是一种电磁波，可以在真空中传播，不需要介质。",
        "在同一种均匀介质里，光沿直线传播。",
        "光在玻璃中约减慢三成，在水中的速度约为真空中的四分之三。",
        "光线从一种介质进入另一种介质时，传播方向通常会发生改变。",
        "把一支笔斜插进装水的透明杯子里，从侧面看，水面上下的笔仿佛断成了两截。",
        "太阳光经过棱镜后会分成红橙黄绿蓝紫几条色带。",
    ])},
    {"name": "夹具资料-声学.txt", "text": "\n".join([
        "声音是物体的振动通过介质传播形成的波。",
        "声音不能在真空中传播，它必须有介质。",
        "声音在固体中传播一般快于液体，液体中快于气体。",
        "在 15 摄氏度的空气中，声音的传播速度约为每秒 340 米。",
        "用手掌轻触喉咙说话时，能感觉到声带的振动。",
    ])},
    {"name": "夹具资料-色彩.txt", "text": "\n".join([
        "人眼看到颜色，靠的是视网膜上的三种视锥细胞。",
        "红绿蓝三种光按不同比例混合，可以配出大部分颜色。",
        "把红色和绿色颜料混在一起，得到的是暗黄或棕色。",
        "光的三原色相加变亮，颜料三原色相减变暗。",
    ])},
]

TITLES = ["测试展项一", "测试展项二", "测试展项三"]
SECONDS = [45, 50, 48]

MAIN = ("这段讲解用来说明夹具的形状：先讲观众能直接看到的现象，再交代背后的原理，"
        "最后留一句可以在展项现场验证的提示。它需要足够长，落在八十到四百字的区间内，"
        "这样时长门才会按字数先放行，再由实测秒数做最终判断。")


def make_mp3(out_path, seconds):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
           "-i", "anullsrc=r=24000:cl=mono", "-t", str(seconds),
           "-b:a", "128k", "-ac", "1", "-ar", "24000", out_path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return os.path.getsize(out_path)


def main():
    db_path, audio_dir = sys.argv[1], sys.argv[2]
    pid = sys.argv[3] if len(sys.argv) > 3 else "fixture001"

    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        os.environ.pop(key, None)
    os.environ["STUDIO_DB"] = db_path
    os.environ["STUDIO_AUDIO_DIR"] = audio_dir
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import studio_server as S

    S.initialize()
    project = S.create_project(name="走查夹具项目", audience="亲子观众", language="中文",
                              brief="走查用夹具：三段测试资料、三个展项、三段已合成音频。",
                              materials=MATERIALS, project_id=pid)
    folder = os.path.join(audio_dir, pid)
    os.makedirs(folder, exist_ok=True)

    exhibits, audio = [], {}
    for index, material in enumerate(project["materials"]):
        ex_id = material["id"]
        src_id = "SRC-%03d" % (index + 1)
        source = next(s for s in project["sources"] if s["id"] == src_id)
        facts = [
            {"id": "F-%03d" % (n + 1), "text": para["text"], "quote": para["text"],
             "source_ref": para["id"], "verified": True}
            for n, para in enumerate(source["paragraphs"][:3])
        ]
        exhibits.append({
            "id": ex_id, "title": TITLES[index],
            "material": material["material"], "source_refs": [src_id],
            "facts": facts,
            "main": {"text": MAIN, "fact_ids": [f["id"] for f in facts]},
            "simplified": {"text": "简单说：" + facts[0]["quote"]},
            "followups": [{"q": "为什么会这样？", "a": "资料里给出的解释是：" + facts[0]["quote"]}],
            "fallback": [{"q": "资料没有覆盖的问题？", "a": "这份资料没有写到，建议现场工作人员补充。"}],
            "issues": [], "verified": True,
        })
        filename = "%s-breeze-%s.mp3" % (ex_id, hashlib.sha256(ex_id.encode()).hexdigest()[:12])
        path = os.path.join(folder, filename)
        size = make_mp3(path, SECONDS[index])
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        audio[ex_id] = {
            "path": os.path.join(pid, filename), "filename": filename, "bytes": size,
            "sha256": digest, "engine": "breeze", "voice": "voc_rc894j8q2auu",
            "model": "breeze-tts-2", "format": "mp3", "mime": "audio/mpeg",
            "chars": len(MAIN), "elapsed_ms": 0, "fallback_errors": [], "at": S.now(),
        }

    project["exhibits"] = exhibits
    project["audio"] = audio
    project["authorization"] = {"confirmed_by": "馆方负责人", "note": "夹具资料授权", "at": S.now()}
    tests = S.content_tests(project)          # 用服务端自己的判据算一遍
    project["tests"] = tests
    project["status"] = "tested" if all(t["status"] == "passed" for t in tests) else "awaiting_confirmation"
    project["run_version"] = 1
    project["version"] = 0.2
    S.save(project)

    for kind, detail in (
        ("run", {"message": "开始为 3 个展项抽取事实"}),
        ("receive", {"step": "receive", "label": "资料接收", "state": "done"}),
        ("locate", {"step": "locate", "label": "来源定位", "state": "done"}),
        ("cards", {"step": "cards", "label": "知识卡", "state": "done"}),
        ("draft", {"step": "draft", "label": "讲解与问答", "state": "done"}),
        ("run.finished", {"message": "生成完成：3 个展项，0 处待核验"}),
        ("tests", {"message": "自测 %d/%d 通过" % (sum(1 for t in tests if t["status"] == "passed"), len(tests))}),
        ("voice", {"message": "已合成 3 段语音", "ok": True}),
    ):
        S.event(pid, kind, detail)

    print(json.dumps({
        "id": pid, "name": project["name"], "status": project["status"],
        "titles": TITLES, "audio": [audio[e["id"]]["filename"] for e in exhibits],
        "tests": [{"name": t["name"], "status": t["status"]} for t in tests],
        "paragraphs": sum(len(s["paragraphs"]) for s in project["sources"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
