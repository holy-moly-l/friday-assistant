"""Opt-in local diagnostics. Never log image bytes, credentials or full requests."""
import json
import os
import sys


def trace(stage, message='', **fields):
    if os.environ.get('FRIDAY_DEBUG', '').lower() not in ('1', 'true', 'yes'):
        return
    details = json.dumps(fields, ensure_ascii=False, default=str) if fields else ''
    print(f'[{stage}] {message} {details}'.rstrip(), file=sys.stderr, flush=True)
