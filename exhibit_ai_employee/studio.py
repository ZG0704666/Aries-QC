import hashlib
import io
import json
import os
import re
import sqlite3
import time
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


class StudioError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


class Studio:
    def __init__(self, database):
        self.database = str(database)
        self.assets = Path(database).parent / 'studio-assets'
        with self.connect() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS studio_projects (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS studio_sessions (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, body TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS studio_events (id INTEGER PRIMARY KEY, project_id TEXT, created_at TEXT, kind TEXT, detail TEXT)')
            connection.execute('CREATE TABLE IF NOT EXISTS studio_calls (id INTEGER PRIMARY KEY, project_id TEXT, created_at TEXT, elapsed_ms INTEGER, outcome TEXT, usage TEXT)')
            for row in connection.execute('SELECT id,body FROM studio_projects').fetchall():
                project = json.loads(row['body'])
                if project['status'] in ('testing', 'synthesizing', 'revising'):
                    project['status'] = 'approved' if project.get('review') else 'draft'
                    project['error'] = '服务重启，中断的操作需要重新执行'
                    self.save(connection, project)

    def connect(self):
        connection = sqlite3.connect(self.database, timeout=20, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA busy_timeout=20000')
        return connection

    def save(self, connection, project):
        project['updated_at'] = stamp()
        connection.execute('INSERT OR REPLACE INTO studio_projects VALUES (?,?)', (project['id'], json.dumps(project, ensure_ascii=False)))

    def event(self, project_id, kind, detail):
        with self.connect() as connection:
            connection.execute('INSERT INTO studio_events(project_id,created_at,kind,detail) VALUES(?,?,?,?)', (project_id, stamp(), kind, json.dumps(detail, ensure_ascii=False)))

    def get(self, project_id, connection=None):
        if connection is None:
            with self.connect() as current:
                return self.get(project_id, current)
        row = connection.execute('SELECT body FROM studio_projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise StudioError('项目不存在', 404)
        return json.loads(row['body'])

    def reserve(self, project_id, data, allowed, next_status):
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            project = self.get(project_id, connection)
            if data.get('expected_version') != project['version']:
                raise StudioError('内容版本已经变化，请刷新后重试', 409)
            if project['status'] not in allowed:
                raise StudioError('当前状态不能执行此操作：' + project['status'], 409)
            project['status'] = next_status
            self.save(connection, project)
            connection.commit()
        return project

    def model(self, messages, project_id=None):
        key = os.environ.get('AI_API_KEY') or os.environ.get('DEEPSEEK_API_KEY')
        if not key:
            raise StudioError('未配置真实模型凭据', 503)
        base = os.environ.get('AI_BASE_URL', 'https://api.deepseek.com/v1').rstrip('/')
        body = {'model': os.environ.get('AI_MODEL', 'deepseek-chat'), 'messages': messages, 'temperature': 0, 'response_format': {'type': 'json_object'}, 'max_tokens': 5000}
        request = urllib.request.Request(base + '/chat/completions', data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        started = time.monotonic()
        usage, outcome = {}, 'failed'
        self.event(project_id, 'model.started', {'message': '正在调用模型，整理原文事实与交互内容'})
        try:
            with urllib.request.urlopen(request, timeout=110) as response:
                result = json.load(response)
            usage = result.get('usage', {})
            parsed = json.loads(result['choices'][0]['message']['content'])
            outcome = 'success'
            return parsed
        except Exception as error:
            raise StudioError('模型服务请求失败：' + type(error).__name__, 502) from error
        finally:
            elapsed = int((time.monotonic()-started)*1000)
            with self.connect() as connection:
                connection.execute('INSERT INTO studio_calls(project_id,created_at,elapsed_ms,outcome,usage) VALUES(?,?,?,?,?)', (project_id, stamp(), elapsed, outcome, json.dumps(usage)))
            self.event(project_id, 'model.' + outcome, {'message': '模型请求完成' if outcome == 'success' else '模型请求失败', 'elapsed_ms': elapsed, 'usage': usage})

    def normalize(self, data):
        items = data.get('exhibits')
        if not isinstance(items, list) or not 1 <= len(items) <= 12:
            raise StudioError('请输入1至12个展项')
        cleaned, seen = [], set()
        for item in items:
            if not isinstance(item, dict):
                raise StudioError('展项格式不正确')
            exhibit_id = str(item.get('exhibit_id', '')).strip()
            text = str(item.get('source_text', '')).strip()
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', exhibit_id) or exhibit_id in seen:
                raise StudioError('展项编号必须唯一，限字母数字下划线')
            if not 20 <= len(text) <= 18000:
                raise StudioError('每项资料需要20至18000字')
            cleaned.append({'exhibit_id': exhibit_id, 'source_name': str(item.get('source_name') or exhibit_id)[:200], 'source_text': text})
            seen.add(exhibit_id)
        if sum(len(item['source_text']) for item in cleaned) > 45000:
            raise StudioError('资料合计不能超过45000字')
        return cleaned
