"""OpenAI 兼容模型客户端。数字与事实不交给模型；模型只做规范编译和文字归纳。"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass
class LLMStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'calls': self.calls,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'seconds': round(self.seconds, 2),
            'errors': self.errors,
        }


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 120,
                 max_calls: int = 6, disable_thinking: bool = True):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_calls = max_calls
        self.disable_thinking = disable_thinking
        self.stats = LLMStats()

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def chat_json(self, system: str, user: str, max_tokens: int = 3000) -> dict:
        content = self.chat(system, user, max_tokens=max_tokens)
        return extract_json(content)

    def chat(self, system: str, user: str, max_tokens: int = 3000) -> str:
        if not self.available:
            raise LLMError('未配置模型服务（base_url / model / api_key）')
        if self.stats.calls >= self.max_calls:
            raise LLMError(f'本次运行模型调用已达上限 {self.max_calls} 次')
        body: dict[str, Any] = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
            'max_tokens': max_tokens,
            'temperature': 0.1,
            'stream': False,
        }
        if self.disable_thinking:
            body['chat_template_kwargs'] = {'enable_thinking': False}
        request = urllib.request.Request(
            self.base_url + '/chat/completions',
            data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
            headers={
                'Authorization': 'Bearer ' + self.api_key,
                'Content-Type': 'application/json',
                'User-Agent': 'AriesQC-Employee/0.1',
            },
        )
        started = time.time()
        self.stats.calls += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(4_000_000)
            data = json.loads(raw)
        except urllib.error.HTTPError as error:
            self.stats.errors.append(f'HTTP {error.code}')
            raise LLMError(f'模型服务 HTTP {error.code}；未记录上游正文') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            self.stats.errors.append('连接失败或超时')
            raise LLMError('模型服务连接失败或超时；本次未完成，不编造结果') from None
        except (UnicodeError, json.JSONDecodeError):
            self.stats.errors.append('非 JSON 响应')
            raise LLMError('模型服务返回非 JSON 响应') from None
        finally:
            self.stats.seconds += time.time() - started
        try:
            message = data['choices'][0]['message']
            content = message.get('content') or ''
        except (KeyError, IndexError, TypeError):
            self.stats.errors.append('响应结构异常')
            raise LLMError('模型响应结构异常，未获得 content') from None
        usage = data.get('usage') or {}
        self.stats.input_tokens += int(usage.get('prompt_tokens') or 0)
        self.stats.output_tokens += int(usage.get('completion_tokens') or 0)
        if not content.strip():
            reasoning = message.get('reasoning') or ''
            hint = '（模型只输出了思考过程）' if reasoning else ''
            raise LLMError('模型返回空 content' + hint + '，请检查模型是否支持禁用思考')
        return content


def extract_json(text: str) -> dict:
    raw = text.strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```[a-zA-Z]*\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find('{')
        end = raw.rfind('}')
        if start < 0 or end <= start:
            raise LLMError('模型输出不是 JSON 对象') from None
        try:
            value = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            raise LLMError('模型输出 JSON 无法解析') from None
    if not isinstance(value, dict):
        raise LLMError('模型输出必须是 JSON 对象')
    return value