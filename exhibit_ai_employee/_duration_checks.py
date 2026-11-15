"""时长门回归：证明「主讲解时长约 45 秒」这一条真的在读音频，而不是还在数汉字。

对手是四种情况：达标、超长、音频登记了但文件丢了、根本没有音频。
判据不能只看 PASS/FAIL，还要看它给出的理由里有没有真实秒数——否则一个永远失败
或永远通过的门也会「看起来在工作」。

隔离：音频目录与数据库都指向临时目录，不碰 audio/ 与 studio.sqlite3。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, ".")

WORK = tempfile.mkdtemp(prefix="studio_duration_")
os.environ["STUDIO_AUDIO_DIR"] = os.path.join(WORK, "audio")
os.environ["STUDIO_DB"] = os.path.join(WORK, "studio.sqlite3")
os.environ.pop("FFPROBE_BIN", None)

import studio_server as S  # noqa: E402

S.initialize()
FFMPEG = shutil.which("ffmpeg")
results = []


def record(ok, name, detail):
    results.append((ok, name, detail))


def make_mp3(path, seconds):
    """生成一段指定秒数的静音 MP3，作为「已知真实时长」的对照组。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    done = subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "anullsrc=r=24000:cl=mono", "-t", str(seconds), "-b:a", "32k", path],
        capture_output=True, timeout=120)
    return done.returncode == 0 and os.path.isfile(path)


def project_with(audio_seconds=None, register_only=False, project_id="durfix"):
    """构造一个内容全合规、只有音频状态不同的项目。"""
    project = {
        "id": project_id,
        "name": "时长门对照项目", "version": 0.1, "status": "draft", "tests": [],
        "materials": [{"id": "EX01", "title": "光的折射"}],
        "exhibits": [{
            "id": "EX01", "title": "光的折射",
            "main": {"text": "主" * 160},
            "facts": [{"id": "F-001", "verified": True, "text": "x", "source_ref": "SRC-001·P001"},
                      {"id": "F-002", "verified": True, "text": "y", "source_ref": "SRC-001·P002"}],
            "followups": [{"q": "问", "a": "答"}],
            "fallback": [{"q": "问", "a": "答"}],
            "source_refs": ["SRC-001"],
            "verified": True,
        }],
        "sources": [],
        "issues": [],
        "audio": {},
    }
    if audio_seconds is not None:
        filename = "EX01-test-%ds.mp3" % audio_seconds
        path = os.path.join(S.tts.AUDIO_ROOT, project_id, filename)
        if not register_only:
            if not make_mp3(path, audio_seconds):
                raise SystemExit("生成测试音频失败，检查 ffmpeg")
        project["audio"]["EX01"] = {"filename": filename, "engine": "test", "format": "mp3"}
    return project

def duration_case(project):
    for test in S.content_tests(project):
        if "时长" in test["name"]:
            return test
    return {"status": "missing", "detail": ""}


def main():
    if not FFMPEG:
        raise SystemExit("未找到 ffmpeg，无法构造对照组")

    # 1 达标：真实 45 秒 → 通过，且理由里必须出现实测秒数
    test = duration_case(project_with(audio_seconds=45, project_id="dur-45"))
    record(test["status"] == "passed" and "45" in test["detail"] and "秒" in test["detail"],
           "真实 45 秒音频应通过时长门", "status=%s detail=%s" % (test["status"], test["detail"][:120]))

    # 2 超长：真实 70 秒 → 必须失败，并指出实测值
    test = duration_case(project_with(audio_seconds=70, project_id="dur-70"))
    record(test["status"] == "failed" and "70" in test["detail"],
           "实测 70 秒应被时长门拦下", "status=%s detail=%s" % (test["status"], test["detail"][:120]))

    # 3 过短：真实 12 秒 → 必须失败
    test = duration_case(project_with(audio_seconds=12, project_id="dur-12"))
    record(test["status"] == "failed" and "12" in test["detail"],
           "实测 12 秒应被时长门拦下", "status=%s detail=%s" % (test["status"], test["detail"][:120]))

    # 4 登记了音频但文件不在磁盘上 → 必须失败（不许当通过）
    test = duration_case(project_with(audio_seconds=45, register_only=True, project_id="dur-missing"))
    record(test["status"] == "failed" and "读不出时长" in test["detail"],
           "音频文件丢失时不得当作时长已核", "status=%s detail=%s" % (test["status"], test["detail"][:120]))

    # 5 完全没有音频 → 通过，但理由必须写明只核了字数
    test = duration_case(project_with(project_id="dur-none"))
    record(test["status"] == "passed" and "未核实测时长" in test["detail"],
           "无音频时写明只核字数、未核实测时长",
           "status=%s detail=%s" % (test["status"], test["detail"][:120]))

    # 6 ffprobe 不可用 + 有音频 → 不能假装通过
    os.environ["FFPROBE_BIN"] = os.path.join(WORK, "no-such-ffprobe")
    test = duration_case(project_with(audio_seconds=45, project_id="dur-noprobe"))
    record(test["status"] == "failed", "ffprobe 缺失时不得静默通过",
           "status=%s detail=%s" % (test["status"], test["detail"][:120]))
    os.environ.pop("FFPROBE_BIN", None)

    # 7 实测结果要回写进项目，交付单才能引用（否则每次都重算，历史记录永远空着）
    project = project_with(audio_seconds=45, project_id="dur-write")
    S.content_tests(project)
    record(project["audio"]["EX01"].get("duration_s") == 45.0,
           "实测时长应回写进项目音频记录",
           "duration_s=%s" % project["audio"]["EX01"].get("duration_s"))

    # 8 导出链路上的时长必须来自实测
    markdown = S.build_export_markdown(project)
    record("45.0 秒" in markdown and "实测时长" in markdown,
           "交付稿应写出实测时长", [l for l in markdown.splitlines() if "音频：" in l][:1])

    print()
    fails = 0
    for ok, name, detail in results:
        print(("PASS " if ok else "FAIL ") + name + " | " + str(detail))
        if not ok:
            fails += 1
    print("\n%d/%d 通过" % (len(results) - fails, len(results)))
    shutil.rmtree(WORK, ignore_errors=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
