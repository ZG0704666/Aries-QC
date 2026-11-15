#!/usr/bin/env python3
"""真实 TTS 合成：把展项主讲解合成为可下发的 MP3 文件。

引擎选择顺序（auto 模式）：
1. Breeze（breezeblue.ai，商用授权接口，需 BREEZE_API_KEY）—— 交付首选
2. edge-tts（微软神经网络音色，需联网，免费无授权确认）—— 未配 Key 时的过渡
3. Windows SAPI（本机离线兜底）—— 无网络时仍能产出音频，但音质明显较差

设计原则（与项目其余部分一致）：
- 合成失败必须如实抛出，绝不返回静默的假成功或空文件；
- 产出物记录 sha256、字节数、时长、音色、引擎、耗时，供交付包与验收单核对；
- 不把「合成成功」等同于「客户验收通过」。
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUDIO_ROOT = Path(os.environ.get("STUDIO_AUDIO_DIR", ROOT / "audio"))

# 各引擎的默认音色。Breeze 的音色 ID 来自 GET /v1/voices，不是自然语言名字。
BREEZE_VOICE = os.environ.get("BREEZE_VOICE_ID", "voc_rc894j8q2auu")  # 知绘小姐：明亮干脆、能干亲近
BREEZE_MODEL = os.environ.get("BREEZE_MODEL_ID", "breeze-tts-2")
EDGE_VOICE = os.environ.get("STUDIO_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
EDGE_RATE = os.environ.get("STUDIO_TTS_RATE", "+0%")

# 逐句合成的分句符：长句整段合成容易出现不自然的停顿，且单次请求过大易失败。
SENTENCE = re.compile(r"[^。！？；\n]+[。！？；\n]?")


class TTSError(RuntimeError):
    """合成失败。engine 指明是哪个引擎失败，便于判断是网络问题还是配置问题。"""

    def __init__(self, message, engine=None, detail=None):
        self.engine = engine
        self.detail = detail
        super().__init__(("[%s] " % engine if engine else "") + message)


def status():
    """报告本地 TTS 能力，不发起任何网络请求。"""
    result = {
        "breeze_voice": BREEZE_VOICE,
        "breeze_model": BREEZE_MODEL,
        "edge_voice": EDGE_VOICE,
        "rate": EDGE_RATE,
        "output_dir": str(AUDIO_ROOT),
        "breeze": bool(os.environ.get("BREEZE_API_KEY", "").strip()),
        "edge_tts": False,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "sapi": False,
    }
    try:
        import edge_tts  # noqa: F401
        result["edge_tts"] = True
    except Exception:
        pass
    if os.name == "nt" and shutil.which("powershell"):
        result["sapi"] = True
    # 首选顺序：breeze > edge > sapi
    engines = []
    if result["breeze"]:
        engines.append("breeze")
    if result["edge_tts"]:
        engines.append("edge-tts")
    if result["sapi"]:
        engines.append("sapi")
    result["engines"] = engines
    result["ready"] = bool(engines)
    return result


def _probe_mp3(data):
    """不依赖外部库判断 MP3 是否可播：检查 ID3 或 MPEG 帧同步字。"""
    if len(data) < 4:
        return False
    return data.startswith(b"ID3") or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0)


def probe_media(path):
    """用 ffprobe 读**实际音频**的时长/码率/采样率。

    为什么不按字节数除码率估：那样得到的不是实测值，一旦容器有变（WAV 兜底、
    变码率）就会算错，而时长门正是要拿它当验收依据。读不到就返回 None，
    由调用方如实报「未采集」，绝不编一个数字顶上。
    """
    exe = os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe")
    if not exe:
        return None
    try:
        done = subprocess.run(
            [exe, "-v", "error", "-show_entries",
             "format=duration,bit_rate:stream=codec_name,sample_rate,channels",
             "-of", "json", str(path)],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    try:
        data = json.loads(done.stdout.decode("utf-8", "replace") or "{}")
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (ValueError, json.JSONDecodeError, TypeError):
        return None
    if duration <= 0:
        return None
    stream = (data.get("streams") or [{}])[0] or {}
    bitrate = (data.get("format") or {}).get("bit_rate")
    sample_rate = stream.get("sample_rate")
    return {
        "duration_s": round(duration, 2),
        "bitrate_kbps": int(int(bitrate) / 1000) if bitrate else None,
        "codec": stream.get("codec_name"),
        "sample_rate": int(sample_rate) if sample_rate else None,
        "channels": stream.get("channels"),
    }


def _synthesize_breeze(text, voice=None):
    """用 Breeze 商用接口合成，返回 (mp3_bytes, extra_meta)。

    复用 breeze.py 里已写的标准库客户端：它会校验 HTTPS、拒绝重定向、
    校验返回确实是 audio/mpeg 且是合法 MP3 帧，并把密钥从异常信息里抹掉。
    """
    try:
        import breeze
    except ImportError as error:
        raise TTSError("breeze.py 不可用", "breeze", str(error))
    if not os.environ.get("BREEZE_API_KEY", "").strip():
        raise TTSError("未配置 BREEZE_API_KEY", "breeze")
    chosen = (voice or BREEZE_VOICE).strip()
    if chosen:
        os.environ["BREEZE_VOICE_ID"] = chosen
    try:
        audio, mime, meta = breeze.synthesize(text)
    except breeze.BreezeError as error:
        raise TTSError(str(error), "breeze", str(error)[:500]) from None
    except Exception as error:
        raise TTSError("%s: %s" % (type(error).__name__, error), "breeze",
                       str(error)[:500]) from None
    if not _probe_mp3(audio):
        raise TTSError("返回的字节不是可播放的 MP3", "breeze")
    return audio, {"mime": mime or "audio/mpeg", "format": "mp3",
                   "breeze_voice": meta.get("voice_id"), "breeze_model": meta.get("model_id")}


def _synthesize_edge(text, voice, rate):
    """用 edge-tts 合成，返回 (mp3_bytes, extra_meta)。"""
    try:
        import edge_tts
    except ImportError as error:
        raise TTSError("edge-tts 未安装", "edge-tts", str(error))

    async def run():
        chunks = bytearray()
        boundaries = 0
        communicator = edge_tts.Communicate(text, voice, rate=rate)
        async for chunk in communicator.stream():
            if chunk["type"] == "audio":
                chunks.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries += 1
        return bytes(chunks), boundaries

    try:
        audio, boundaries = asyncio.run(run())
    except Exception as error:  # 网络、403、音色不存在等统一归到这里
        raise TTSError("%s: %s" % (type(error).__name__, error), "edge-tts",
                       str(error)[:500]) from None
    if not _probe_mp3(audio):
        raise TTSError("返回的字节不是可播放的 MP3", "edge-tts")
    return audio, {"word_boundaries": boundaries}


SAPI_VOICES = {"Microsoft Huihui Desktop", "Microsoft Yaoyao Desktop", "Microsoft Kangkang Desktop"}


def _synthesize_sapi(text, voice=None):
    """Windows SAPI 离线兜底：先合成 WAV，有 ffmpeg 时再转 MP3。"""
    if os.name != "nt" or not shutil.which("powershell"):
        raise TTSError("非 Windows 环境，SAPI 不可用", "sapi")
    chosen = voice if voice in SAPI_VOICES else "Microsoft Huihui Desktop"
    workdir = Path(tempfile.mkdtemp(prefix="studio_tts_"))
    wav = workdir / "out.wav"
    # 文本经文件传入，避免中文标点被 PowerShell 解析；
    # -EncodedCommand 需要 UTF-16LE 的 Base64，这里改用脚本文件更直观。
    script = workdir / "say.ps1"
    script.write_text(
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        "$s.SelectVoice('%s')\n"
        "$s.SetOutputToWaveFile('%s')\n"
        "$s.Speak([IO.File]::ReadAllText('%s', [Text.Encoding]::UTF8))\n"
        "$s.Dispose()\n" % (chosen, wav, workdir / "text.txt"),
        encoding="utf-8-sig",
    )
    (workdir / "text.txt").write_text(text, encoding="utf-8")
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        raise TTSError("SAPI 合成超时", "sapi") from None
    if done.returncode != 0 or not wav.is_file() or wav.stat().st_size < 1024:
        detail = (done.stderr or b"").decode("utf-8", "replace")[:500]
        raise TTSError("SAPI 未产出音频", "sapi", detail)

    if not shutil.which("ffmpeg"):
        # 没有 ffmpeg 就交付 WAV：格式不同必须如实标注，不能谎称 MP3。
        return wav.read_bytes(), {"format": "wav", "mime": "audio/wav", "sapi_voice": chosen}

    mp3 = workdir / "out.mp3"
    conv = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
         "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3)],
        capture_output=True, timeout=180,
    )
    if conv.returncode != 0 or not mp3.is_file():
        detail = (conv.stderr or b"").decode("utf-8", "replace")[:500]
        raise TTSError("ffmpeg 转码失败", "sapi", detail)
    return mp3.read_bytes(), {"format": "mp3", "mime": "audio/mpeg", "sapi_voice": chosen}


def split_long(text, limit=1200):
    """按句子拼装，保证单次请求不超过 limit 字。返回已合成的完整句组。"""
    parts, current = [], ""
    for sentence in SENTENCE.findall(text):
        if not sentence:
            continue
        if len(current) + len(sentence) > limit and current:
            parts.append(current)
            current = sentence
        else:
            current += sentence
    if current.strip():
        parts.append(current)
    return [p for p in parts if p.strip()]


def synthesize(project_id, exhibit_id, text, voice=None, engine=None):
    """合成一个展项的讲解音频，落盘并返回元数据。

    返回 dict 含：path（相对路径）、bytes、sha256、engine、voice、format、mime、elapsed_ms。
    失败抛 TTSError，不写任何占位文件。
    """
    text = (text or "").strip()
    if not text:
        raise TTSError("主讲解为空，没有可合成的文本")
    if len(text) > 20000:
        raise TTSError("文本超过 20000 字，请拆分后再合成")

    # 音色按引擎解析：Breeze 用 voc_* ID，edge 用 zh-CN-*Neural，SAPI 用系统音色名。
    requested = (engine or os.environ.get("STUDIO_TTS_ENGINE") or "auto").strip().lower()
    # 输出文件名带上内容哈希前缀：文本改了必然换文件名，避免浏览器缓存旧音频。
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    out_dir = AUDIO_ROOT / project_id
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    errors = []
    audio = meta = used = None

    caps = status()
    order = ["breeze", "edge-tts", "sapi"] if requested in ("auto", "") else [requested]
    for name in order:
        try:
            if name == "breeze":
                audio, meta = _synthesize_breeze(text, voice)
            elif name == "edge-tts":
                audio, meta = _synthesize_edge(text, voice or EDGE_VOICE, EDGE_RATE)
            elif name == "sapi":
                audio, meta = _synthesize_sapi(text, None)
            else:
                raise TTSError("未知引擎：" + name)
            used = name
            break
        except TTSError as error:
            errors.append({"engine": name, "error": str(error)})
            if requested not in ("auto", ""):
                raise  # 指定了引擎就不偷偷降级，避免把低音质产物当高质量交付
            continue

    if audio is None:
        raise TTSError("所有 TTS 引擎均失败：" + json.dumps(errors, ensure_ascii=False),
                       detail=json.dumps(errors, ensure_ascii=False))

    fmt = meta.get("format", "mp3")
    filename = "%s-%s-%s.%s" % (exhibit_id, used, digest, fmt)
    target = out_dir / filename
    target.write_bytes(audio)

    if used == "breeze":
        used_voice = meta.get("breeze_voice") or BREEZE_VOICE
    elif used == "edge-tts":
        used_voice = voice or EDGE_VOICE
    else:
        used_voice = meta.get("sapi_voice")

    elapsed = int((time.monotonic() - started) * 1000)
    # 时长在合成这一刻就实测记录下来：交付单和历史记录都靠它，不能事后靠字数推算。
    probed = probe_media(target) or {}
    info = {
        "path": str(target.relative_to(ROOT)) if ROOT in target.parents else str(target),
        "filename": filename,
        "bytes": len(audio),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "engine": used,
        "voice": used_voice,
        "model": meta.get("breeze_model") or (BREEZE_MODEL if used == "breeze" else None),
        "format": fmt,
        "mime": meta.get("mime", "audio/mpeg"),
        "chars": len(text),
        "duration_s": probed.get("duration_s"),
        "bitrate_kbps": probed.get("bitrate_kbps"),
        "sample_rate": probed.get("sample_rate"),
        "elapsed_ms": elapsed,
        "fallback_errors": errors,
    }
    return info
