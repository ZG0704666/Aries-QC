"""Standard-library Breeze TTS2 client; configuration comes only from env."""

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class BreezeError(RuntimeError):
    def __init__(self, code, detail, http_status=None, metadata=None):
        self.code = code
        self.detail = detail
        self.http_status = http_status
        self.metadata = metadata or {}
        label = "Breeze %s" % code
        if http_status is not None:
            label += " (HTTP %s)" % http_status
        super().__init__("%s: %s" % (label, detail))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _redact(value, api_key):
    if isinstance(value, str):
        return value.replace(api_key, "[REDACTED]") if api_key else value
    if isinstance(value, dict):
        return {_redact(key, api_key): _redact(item, api_key) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, api_key) for item in value]
    return value


def _config():
    api_key = os.environ.get("BREEZE_API_KEY", "").strip()
    voice_id = os.environ.get("BREEZE_VOICE_ID", "").strip()
    model_id = os.environ.get("BREEZE_MODEL_ID", "").strip() or "breeze-tts-2"
    base_url = os.environ.get("BREEZE_BASE_URL", "").strip() or "https://api.breeze.blue"
    try:
        parsed = urllib.parse.urlsplit(base_url)
        valid_base = (
            parsed.scheme == "https" and parsed.hostname and parsed.port != 0
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and parsed.path in ("", "/")
            and not any(character.isspace() for character in base_url)
        )
    except ValueError:
        valid_base = False
    if not valid_base:
        raise BreezeError("INVALID_CONFIG", "BREEZE_BASE_URL must be an HTTPS origin without credentials, path, query or fragment")
    if any(character.isspace() for character in api_key):
        raise BreezeError("INVALID_CONFIG", "BREEZE_API_KEY contains whitespace")
    if len(model_id) > 120:
        raise BreezeError("INVALID_CONFIG", "BREEZE_MODEL_ID exceeds 120 characters")
    endpoint = base_url.rstrip("/") + "/v1/text-to-speech/" + urllib.parse.quote(voice_id, safe="")
    return {"api_key": api_key, "voice_id": voice_id, "model_id": model_id, "endpoint": endpoint}


def status():
    """Return local configuration readiness; never make a provider request."""
    result = {"provider": "breeze", "mode": "live", "configured": False, "verified": False}
    try:
        config = _config()
    except BreezeError as error:
        result.update(code=error.code, error=error.detail)
        return result
    missing = [name for name, value in (
        ("BREEZE_API_KEY", config["api_key"]),
        ("BREEZE_VOICE_ID", config["voice_id"]),
    ) if not value]
    result.update(_redact({
        "configured": not missing,
        "api_key_configured": bool(config["api_key"]),
        "voice_id": config["voice_id"],
        "model_id": config["model_id"],
        "language_code": "zh",
        "output_format": "mp3_24000_128",
        "endpoint": config["endpoint"],
        "missing": missing,
    }, config["api_key"]))
    return result


def synthesize(text):
    """Return (audio_bytes, mime, metadata), or raise BreezeError; no retries."""
    if not isinstance(text, str) or not text.strip():
        raise BreezeError("INVALID_INPUT", "text must be a non-empty string")
    if len(text) > 2000:
        raise BreezeError("INVALID_INPUT", "text exceeds the provider maximum of 2000 characters; most accounts allow 1000")
    config = _config()
    api_key = config["api_key"]
    missing = [name for name, value in (
        ("BREEZE_API_KEY", api_key), ("BREEZE_VOICE_ID", config["voice_id"]),
    ) if not value]
    if missing:
        raise BreezeError("NOT_CONFIGURED", "Missing environment variables: " + ", ".join(missing))
    metadata = _redact({
        "provider": "breeze", "mode": "live", "endpoint": config["endpoint"],
        "voice_id": config["voice_id"], "model_id": config["model_id"],
        "language_code": "zh", "output_format": "mp3_24000_128",
    }, api_key)
    payload = json.dumps({
        "text": text, "model_id": config["model_id"], "language_code": "zh",
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        config["endpoint"] + "?output_format=mp3_24000_128&delivery=sync",
        data=payload,
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=90) as response:
            metadata.update({
                "http_status": response.status,
                "history_item_id": response.headers.get("history-item-id"),
                "api_key_id": response.headers.get("x-breeze-api-key-id"),
            })
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            audio = response.read()
            if response.status != 200:
                raise BreezeError("UNEXPECTED_RESPONSE", "Expected synchronous HTTP 200 audio", response.status, _redact(metadata, api_key))
            if mime != "audio/mpeg":
                raise BreezeError("INVALID_AUDIO_RESPONSE", "Expected audio/mpeg, received " + _redact(mime or "missing Content-Type", api_key), response.status, _redact(metadata, api_key))
            if len(audio) < 4 or not (audio.startswith(b"ID3") or (audio[0] == 255 and audio[1] & 224 == 224)):
                raise BreezeError("INVALID_AUDIO_RESPONSE", "Empty or unrecognized MP3 response", response.status, _redact(metadata, api_key))
    except urllib.error.HTTPError as error:
        metadata.update({
            "http_status": error.code,
            "history_item_id": error.headers.get("history-item-id") if error.headers else None,
            "retry_after": error.headers.get("Retry-After") if error.headers else None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        })
        try:
            body = error.read(65536).decode("utf-8", errors="replace")
        except (OSError, http.client.HTTPException):
            body = "Unable to read provider error body"
        finally:
            error.close()
        try:
            provider_error = json.loads(body)
        except ValueError:
            provider_error = None
        code = "HTTP_ERROR"
        detail = body[:2000] or "Provider returned an empty error body"
        if isinstance(provider_error, dict):
            code = str(provider_error.get("code") or code)
            detail = str(provider_error.get("detail") or provider_error.get("error") or detail)[:2000]
            metadata["provider_meta"] = provider_error.get("meta")
        raise BreezeError(_redact(code, api_key), _redact(detail, api_key), error.code, _redact(metadata, api_key)) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        metadata["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        raise BreezeError("TRANSPORT_ERROR", _redact(str(error), api_key), metadata=_redact(metadata, api_key)) from None
    metadata.update({
        "bytes": len(audio), "content_type": mime,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    return audio, mime, _redact(metadata, api_key)
