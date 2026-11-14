"""标尺 CLI：端到端跑一批数据并产出交付包。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from employee.config import Config
from employee.runner import Runner


def main() -> int:
    parser = argparse.ArgumentParser(description='标尺 · AI 数据采集与标注质检专员')
    parser.add_argument('--batch', required=True, help='批次目录（可含多个子批次）')
    parser.add_argument('--spec', required=True, help='规范文件（PDF/MD/TXT/YAML/JSON）')
    parser.add_argument('--no-model', action='store_true', help='跳过模型交叉复核')
    parser.add_argument('--no-llm', action='store_true', help='跳过模型调用（规范编译仍需 YAML/启发式）')
    parser.add_argument('--strict', action='store_true', help='规范有歧义时停下来问人')
    parser.add_argument('--probe-max', type=int, default=0, help='模型最多复核多少张（0=全部）')
    parser.add_argument('--json', action='store_true', help='打印机器可读摘要')
    args = parser.parse_args()

    config = Config.load()
    runner = Runner(
        config,
        batch_path=args.batch,
        spec_path=args.spec,
        options={
            'use_model': not args.no_model,
            'use_llm_summary': not args.no_llm,
            'strict_spec': args.strict,
            'probe_max_images': args.probe_max,
        },
    )
    print(f'运行编号：{runner.run_id}')
    print(f'批次：{args.batch}')
    print(f'规范：{args.spec}')
    runner.start()
    state = runner.state
    print(f"状态：{state['status']}")
    if state.get('error'):
        print(f"错误：{state['error']}")
    for step in state['steps']:
        status = step['status']
        print(f"  [{status:>10}] {step['title']} ({step['duration']}s)")
    if state.get('questions'):
        print('需要人工确认：')
        for question in state['questions']:
            print(' -', question.get('question'))
        print(f'运行目录：{runner.run_dir}')
        return 2
    summary = state.get('summary') or {}
    print('')
    print(summary.get('headline', ''))
    print(f"交付包：{runner.run_dir / 'delivery.zip'}")
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if state['status'] == 'done' else 1


if __name__ == '__main__':
    raise SystemExit(main())