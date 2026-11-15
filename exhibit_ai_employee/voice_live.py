"""Pipecat PCM WebSocket gateway; Python 3.10+ and requirements-voice.txt."""

import asyncio
import contextlib
import hmac
import io
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

LOG = logging.getLogger("voice_live")
FRAMEWORK_VERSION = "0.0.108"


@dataclass
class Settings:
    base_url: str = "http://127.0.0.1:4181"
    studio_token: str = ""
    voice_token: str = ""
    allowed_origins: tuple = ()
    model: str = "small"
    device: str = "auto"
    language: str = "zh"
    local_files_only: bool = True
    timeout: float = 90
    max_seconds: float = 30
    max_connections: int = 4
    vad_start: float = 0.15
    vad_stop: float = 0.6
    voice_id: str = ""
    instructions: str = ""

    @classmethod
    def from_env(cls):
        settings = cls(
            base_url=os.getenv("STUDIO_BASE_URL", cls.base_url).rstrip("/"),
            studio_token=os.getenv("STUDIO_ACCESS_TOKEN", os.getenv("ACCESS_TOKEN", "")),
            voice_token=os.getenv("VOICE_ACCESS_TOKEN", ""),
            allowed_origins=tuple(filter(None, (value.strip() for value in
                os.getenv("VOICE_ALLOWED_ORIGINS", "").split(",")))),
            model=os.getenv("VOICE_STT_MODEL", "small"),
            device=os.getenv("VOICE_STT_DEVICE", "auto"),
            language=os.getenv("VOICE_STT_LANGUAGE", "zh"),
            local_files_only=os.getenv("VOICE_STT_LOCAL_FILES_ONLY", "1") == "1",
            timeout=float(os.getenv("VOICE_REQUEST_TIMEOUT", "90")),
            max_seconds=float(os.getenv("VOICE_MAX_UTTERANCE_SECONDS", "30")),
            max_connections=int(os.getenv("VOICE_MAX_CONNECTIONS", "4")),
            vad_start=float(os.getenv("VOICE_VAD_START_SECONDS", ".15")),
            vad_stop=float(os.getenv("VOICE_VAD_STOP_SECONDS", ".6")),
            voice_id=os.getenv("VOICE_BREEZE_VOICE_ID", ""),
            instructions=os.getenv("VOICE_BREEZE_INSTRUCTIONS", ""),
        )
        settings.validate()
        return settings

    def validate(self):
        parsed = urlsplit(self.base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("STUDIO_BASE_URL must be HTTP(S) without credentials/query")
        if not self.voice_token:
            raise ValueError("VOICE_ACCESS_TOKEN is required")
        if self.device not in {"auto", "cuda", "cpu"}:
            raise ValueError("VOICE_STT_DEVICE must be auto/cuda/cpu")
        if not (1 <= self.max_seconds <= 120 and 1 <= self.max_connections <= 32
                and 0 < self.timeout <= 300 and 0 < self.vad_start <= 1
                and 0.1 <= self.vad_stop <= 3):
            raise ValueError("Voice limits are outside supported ranges")


def gpu_error(error):
    return any(word in str(error).lower() for word in
               ("cuda", "cudnn", "cublas", "driver", "out of memory"))


class LocalWhisper:
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.device = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-stt")

    def load(self, device):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            self.settings.model, device=device,
            compute_type="float16" if device == "cuda" else "int8",
            local_files_only=self.settings.local_files_only,
        )
        self.device = device

    def transcribe_sync(self, pcm):
        import ctranslate2

        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        if self.model is None:
            device = self.settings.device
            if device == "auto":
                try:
                    device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
                except (RuntimeError, OSError):
                    device = "cpu"
            try:
                self.load(device)
            except (RuntimeError, OSError) as error:
                if device != "cuda" or not gpu_error(error):
                    raise
                LOG.warning("CUDA initialization failed; falling back to CPU")
                self.load("cpu")
        for attempt in range(2):
            try:
                segments, _info = self.model.transcribe(
                    audio, language=self.settings.language or None, beam_size=1,
                    vad_filter=False, condition_on_previous_text=False,
                )
                return "".join(segment.text for segment in segments).strip()
            except (RuntimeError, OSError) as error:
                if attempt or self.device != "cuda" or not gpu_error(error):
                    raise
                LOG.warning("CUDA inference failed; falling back to CPU")
                self.model = None
                self.load("cpu")

    async def transcribe(self, pcm):
        return await asyncio.get_running_loop().run_in_executor(
            self.executor, self.transcribe_sync, pcm)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)


def split_tts(text, limit=800):
    for offset in range(0, len(text), limit):
        chunk = text[offset:offset + limit]
        if chunk.strip():
            yield chunk


def decode_tts(data):
    from faster_whisper.audio import decode_audio

    audio = decode_audio(io.BytesIO(data), sampling_rate=24000)
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


class StudioSession:
    def __init__(self, client, settings, project_id, exhibit_id, session_id=""):
        self.client = client
        self.settings = settings
        self.project_id = project_id
        self.exhibit_id = exhibit_id
        self.session_id = session_id
        self.lock = asyncio.Lock()

    async def chat(self, message):
        async with self.lock:
            response = await self.client.post(
                f"/api/studio/projects/{self.project_id}/chat",
                json={"message": message, "exhibit_id": self.exhibit_id,
                      "session_id": self.session_id},
            )
            response.raise_for_status()
            payload = response.json()
            if (not isinstance(payload, dict)
                    or not isinstance(payload.get("answer"), str)
                    or not isinstance(payload.get("citations"), list)
                    or not isinstance(payload.get("kind"), str)
                    or not isinstance(payload.get("session_id"), str)
                    or not payload["session_id"]):
                raise ValueError("Invalid Studio chat response")
            self.session_id = payload["session_id"]
            return {key: payload[key] for key in ("answer", "citations", "kind", "session_id")}

    async def synthesize(self, text):
        response = await self.client.post("/api/tts", json={
            "text": text, "voice_id": self.settings.voice_id,
            "instructions": self.settings.instructions,
        })
        response.raise_for_status()
        path = response.json().get("url", "")
        if not isinstance(path, str) or not re.fullmatch(r"/api/audio/[A-Za-z0-9_-]+\.mp3", path):
            raise ValueError("Breeze must return a local /api/audio/*.mp3 URL")
        chunks = []
        size = 0
        async with self.client.stream("GET", path) as audio:
            audio.raise_for_status()
            async for chunk in audio.aiter_bytes():
                size += len(chunk)
                if size > 16 * 1024 * 1024:
                    raise ValueError("Breeze audio exceeds 16 MiB")
                chunks.append(chunk)
        return await asyncio.to_thread(decode_tts, b"".join(chunks))


def load_pipeline_api():
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.frames.frames import (
        CancelFrame, EndFrame, InputAudioRawFrame, InterruptionFrame,
        OutputAudioRawFrame, OutputTransportMessageFrame,
        OutputTransportMessageUrgentFrame, StartFrame,
        VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.serializers.base_serializer import FrameSerializer, FrameSerializerType
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketParams, FastAPIWebsocketTransport,
    )

    class PCMSerializer(FrameSerializer):
        @property
        def type(self):
            return FrameSerializerType.BINARY

        async def serialize(self, frame):
            if isinstance(frame, OutputAudioRawFrame):
                return frame.audio
            if isinstance(frame, InterruptionFrame):
                return json.dumps({"type": "interrupt"})
            if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
                return json.dumps(frame.message, ensure_ascii=False)
            return None

        async def deserialize(self, data):
            if isinstance(data, bytes) and 0 < len(data) <= 6400 and len(data) % 2 == 0:
                return InputAudioRawFrame(audio=data, sample_rate=16000, num_channels=1)
            raise ValueError("Expected 16kHz mono PCM16 binary packets of at most 200ms")

    class VoiceTurns(FrameProcessor):
        def __init__(self, session, recognizer, settings):
            super().__init__()
            self.session = session
            self.recognizer = recognizer
            self.settings = settings
            self.buffer = bytearray()
            self.speaking = False
            self.overflow = False
            self.turn = 0
            self.reply = None
            self.requests = set()

        async def event(self, kind, **values):
            await self.push_frame(OutputTransportMessageUrgentFrame(
                message={"type": kind, "turn": self.turn, **values}))

        async def stop_reply(self):
            if self.reply and not self.reply.done():
                self.reply.cancel()
                await asyncio.gather(self.reply, return_exceptions=True)
            self.reply = None

        def request_done(self, task):
            self.requests.discard(task)
            if not task.cancelled():
                task.exception()

        async def respond(self, pcm, turn):
            stage = "stt"
            try:
                text = await self.recognizer.transcribe(pcm)
                if turn != self.turn or not text:
                    return
                await self.event("transcript", text=text)
                stage = "chat"
                request = self.create_task(self.session.chat(text), name="studio-chat")
                self.requests.add(request)
                request.add_done_callback(self.request_done)
                answer = await asyncio.shield(request)
                if turn != self.turn:
                    return
                await self.event("answer", **answer)
                stage = "tts"
                for chunk in split_tts(answer["answer"]):
                    audio = await self.session.synthesize(chunk)
                    if turn != self.turn:
                        return
                    await self.event("audio_start", sample_rate=24000)
                    for offset in range(0, len(audio), 960):
                        if turn != self.turn:
                            return
                        await self.push_frame(OutputAudioRawFrame(
                            audio=audio[offset:offset + 960], sample_rate=24000, num_channels=1))
                        await asyncio.sleep(.02)
                await self.event("done", session_id=self.session.session_id)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                LOG.warning("Voice turn failed at %s (%s)", stage, type(error).__name__)
                if turn == self.turn:
                    await self.event("error", stage=stage, error=type(error).__name__)

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if direction == FrameDirection.UPSTREAM:
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, InputAudioRawFrame):
                if not self.overflow:
                    self.buffer.extend(frame.audio)
                    if not self.speaking:
                        keep = int((self.settings.vad_start + .25) * 32000)
                        self.buffer = self.buffer[-keep:]
                    elif len(self.buffer) > self.settings.max_seconds * 32000:
                        self.buffer.clear()
                        self.overflow = True
                        await self.event("error", stage="vad", error="utterance_too_long")
                return
            if isinstance(frame, VADUserStartedSpeakingFrame):
                self.speaking = True
                self.turn += 1
                await self.stop_reply()
                await self.broadcast_interruption()
                await self.event("listening")
                return
            if isinstance(frame, VADUserStoppedSpeakingFrame):
                self.speaking = False
                pcm = bytes(self.buffer)
                self.buffer.clear()
                if not self.overflow and pcm:
                    self.reply = self.create_task(self.respond(pcm, self.turn), name="voice-reply")
                self.overflow = False
                return
            if isinstance(frame, (CancelFrame, EndFrame)):
                await self.stop_reply()
            await self.push_frame(frame, direction)
            if isinstance(frame, StartFrame):
                await self.event("ready", input_sample_rate=16000, output_sample_rate=24000)

        async def cleanup(self):
            await self.stop_reply()
            requests = list(self.requests)
            for request in requests:
                request.cancel()
            await asyncio.gather(*requests, return_exceptions=True)
            await super().cleanup()

    async def run(websocket, session, recognizer, settings):
        transport = FastAPIWebsocketTransport(websocket, FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True,
            audio_in_sample_rate=16000, audio_out_sample_rate=24000,
            add_wav_header=False, serializer=PCMSerializer(),
        ))
        pipeline = Pipeline([
            transport.input(),
            VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(
                start_secs=settings.vad_start, stop_secs=settings.vad_stop))),
            VoiceTurns(session, recognizer, settings), transport.output(),
        ])
        task = PipelineTask(pipeline, params=PipelineParams(
            audio_in_sample_rate=16000, audio_out_sample_rate=24000))

        @transport.event_handler("on_client_disconnected")
        async def disconnected(_transport, _websocket):
            await task.cancel()

        await PipelineRunner(handle_sigint=False).run(task)

    return run


def create_app(settings=None, pipeline_factory=None, recognizer=None, http_transport=None):
    settings = settings or Settings.from_env()
    settings.validate()

    @asynccontextmanager
    async def lifespan(app):
        app.state.run_pipeline = (pipeline_factory or load_pipeline_api)()
        app.state.recognizer = recognizer or LocalWhisper(settings)
        app.state.connections = 0
        async with httpx.AsyncClient(
            base_url=settings.base_url, timeout=settings.timeout, follow_redirects=False,
            headers={"X-Access-Token": settings.studio_token}, transport=http_transport,
        ) as client:
            app.state.client = client
            try:
                yield
            finally:
                app.state.recognizer.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def health():
        return {"ok": True, "framework": f"pipecat-ai=={FRAMEWORK_VERSION}",
                "connections": app.state.connections,
                "stt_loaded": app.state.recognizer.model is not None,
                "stt_device": app.state.recognizer.device,
                "upstream_verified": False, "devices_verified": False}

    @app.get("/", response_class=HTMLResponse)
    async def demo():
        return DEMO_HTML

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        same_origin = str(websocket.url).replace("ws://", "http://", 1).replace(
            "wss://", "https://", 1).rsplit("/", 1)[0]
        if origin and origin not in (settings.allowed_origins or (same_origin,)):
            await websocket.close(code=1008)
            return
        if app.state.connections >= settings.max_connections:
            await websocket.close(code=1013)
            return
        app.state.connections += 1
        try:
            await websocket.accept()
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            if len(raw.encode("utf-8")) > 8192:
                raise ValueError("Start message too large")
            start = json.loads(raw)
            if not isinstance(start, dict):
                raise ValueError("Invalid start")
            token = start.get("token", "")
            if (start.get("type") != "start" or not isinstance(token, str)
                    or not hmac.compare_digest(token.encode(), settings.voice_token.encode())):
                raise ValueError("Authentication failed")
            project = str(start.get("project_id", ""))
            exhibit = str(start.get("exhibit_id", ""))
            session_id = start.get("session_id", "")
            if (not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", project)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", exhibit)
                    or not isinstance(session_id, str) or len(session_id) > 256):
                raise ValueError("Invalid project/exhibit/session")
            session = StudioSession(app.state.client, settings, project, exhibit, session_id)
            await app.state.run_pipeline(websocket, session, app.state.recognizer, settings)
        except WebSocketDisconnect:
            pass
        except (ValueError, asyncio.TimeoutError):
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=1008)
        except Exception as error:
            LOG.warning("Voice connection failed (%s)", type(error).__name__)
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=1011)
        finally:
            app.state.connections -= 1
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close()

    return app


DEMO_HTML = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>展馆实时语音测试</title>
<style>body{font:16px system-ui;max-width:850px;margin:32px auto;padding:16px}
input,button{font:inherit;padding:8px;margin:5px}pre{white-space:pre-wrap;background:#eee;padding:16px}</style>
<h1>展馆实时语音测试</h1><p>请使用耳机；需要 localhost 或 HTTPS 麦克风权限。</p>
<label>网关令牌<input id="token" type="password" autocomplete="off"></label>
<label>项目<input id="project" value="1"></label><label>展品<input id="exhibit" value="A"></label>
<label>会话<input id="session"></label><br>
<button id="connect">连接并开始说话</button><button id="stop">断开</button><pre id="log"></pre>
<script>
const $ = id => document.getElementById(id);
let current = null;
function log(value) { $('log').textContent = (JSON.stringify(value)+'\n'+$('log').textContent).slice(0,16000); }
function flush(state) {
  for (const source of state.sources) { try { source.stop(); } catch {} }
  state.sources.clear(); state.nextTime=0;
}
function close(state) {
  if (!state || state.closed) return;
  state.closed=true; state.ready=false; flush(state);
  state.stream?.getTracks().forEach(track => track.stop());
  state.node?.disconnect(); state.mic?.disconnect(); state.silent?.disconnect();
  if (state.ws && state.ws.readyState<2) state.ws.close();
  state.ctx?.close();
  if (current===state) current=null;
}
$('stop').onclick = () => close(current);
$('connect').onclick = async () => {
  close(current);
  const state={sources:new Set(),nextTime:0,closed:false,ready:false}; current=state;
  try {
    state.ctx=new AudioContext(); await state.ctx.resume();
    state.stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,
      echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    if (state.closed) { state.stream.getTracks().forEach(track=>track.stop()); return; }
    const code=`class Capture extends AudioWorkletProcessor {
      constructor(){super();this.samples=[];this.position=0;this.packet=[];}
      process(inputs){const audio=inputs[0]?.[0];if(!audio)return true;
        for(const sample of audio)this.samples.push(sample);
        const step=sampleRate/16000;
        while(this.position+1<this.samples.length){
          const index=Math.floor(this.position), fraction=this.position-index;
          this.packet.push(this.samples[index]*(1-fraction)+this.samples[index+1]*fraction);
          this.position+=step;
          if(this.packet.length===320){const data=new ArrayBuffer(640),view=new DataView(data);
            this.packet.forEach((value,index)=>view.setInt16(index*2,
              Math.round(Math.max(-1,Math.min(1,value))*32767),true));
            this.port.postMessage(data,[data]);this.packet=[];}}
        const consumed=Math.floor(this.position);this.samples.splice(0,consumed);
        this.position-=consumed;return true;}}
      registerProcessor('capture',Capture);`;
    const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));
    try { await state.ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
    if (state.closed) return;
    state.node=new AudioWorkletNode(state.ctx,'capture');
    state.mic=state.ctx.createMediaStreamSource(state.stream);
    state.silent=state.ctx.createGain();state.silent.gain.value=0;
    state.mic.connect(state.node).connect(state.silent).connect(state.ctx.destination);
    const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
    state.ws=ws;ws.binaryType='arraybuffer';
    ws.onopen=()=>ws.send(JSON.stringify({type:'start',token:$('token').value,
      project_id:$('project').value,exhibit_id:$('exhibit').value,session_id:$('session').value}));
    state.node.port.onmessage=event=>{
      if(state.closed || !state.ready || ws.readyState!==1)return;
      if(ws.bufferedAmount>64000){log({error:'upload_backpressure'});close(state);return;}
      ws.send(event.data);
    };
    ws.onmessage=event=>{
      if(state.closed)return;
      if(typeof event.data==='string'){
        const message=JSON.parse(event.data);log(message);
        if(message.type==='ready')state.ready=true;
        if(message.type==='interrupt')flush(state);
        if(message.session_id)$('session').value=message.session_id;
        return;
      }
      const view=new DataView(event.data), count=view.byteLength/2;
      const buffer=state.ctx.createBuffer(1,count,24000), channel=buffer.getChannelData(0);
      for(let index=0;index<count;index++)channel[index]=view.getInt16(index*2,true)/32768;
      if(state.nextTime-state.ctx.currentTime>3){flush(state);log({error:'playback_backpressure'});}
      const source=state.ctx.createBufferSource();source.buffer=buffer;source.connect(state.ctx.destination);
      const start=Math.max(state.ctx.currentTime+.04,state.nextTime);
      state.nextTime=start+buffer.duration;state.sources.add(source);
      source.onended=()=>state.sources.delete(source);source.start(start);
    };
    ws.onerror=()=>{log({error:'websocket_error'});close(state);};
    ws.onclose=event=>{log({closed:event.code});close(state);};
  } catch(error) {log({error:error.message});close(state);}
};
</script></html>'''


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=os.getenv("VOICE_LOG_LEVEL", "INFO"))
    uvicorn.run(create_app(), host=os.getenv("VOICE_HOST", "127.0.0.1"),
                port=int(os.getenv("VOICE_PORT", "4182")), ws_max_size=8192, ws_max_queue=8)
