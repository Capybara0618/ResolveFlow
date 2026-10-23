"""One immutable original follow-up; an explicitly prepared output and request bound per revision."""

from __future__ import annotations

import argparse
from pathlib import Path

import confirm_policy_focus_live_v1 as driver

OUT = driver.ROOT / 'reports/customer-policy-focus-close-v1/scope-v2'


def prepare(limit=4):
    assert 1 <= limit <= 12
    original = driver.OUT
    try:
        driver.OUT = OUT
        driver.prepare()
        path = OUT / 'manifest.json'
        manifest = driver.read(path)
        manifest.update(model_attempt_limit=limit,
                        scope='one original follow-up after explicit history scope references')
        script = Path(__file__).resolve()
        manifest['files'][script.relative_to(driver.ROOT).as_posix()] = driver.digest(script)
        driver.persist(path, manifest)
    finally:
        driver.OUT = original


def execute():
    original = driver.OUT
    try:
        driver.OUT = OUT
        driver.execute()
    finally:
        driver.OUT = original


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'execute'])
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--max-attempts', type=int, choices=range(1, 13), default=4)
    args = parser.parse_args()
    OUT = args.output.resolve()
    prepare(args.max_attempts) if args.command == 'prepare' else execute()
