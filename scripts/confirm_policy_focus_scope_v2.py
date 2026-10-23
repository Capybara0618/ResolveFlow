"""One original follow-up after explicit discussion references; at most four real model requests."""

from __future__ import annotations

import argparse
from pathlib import Path

import confirm_policy_focus_live_v1 as driver

OUT = driver.ROOT / 'reports/customer-policy-focus-close-v1/scope-v2'


def prepare():
    original = driver.OUT
    try:
        driver.OUT = OUT
        driver.prepare()
        path = OUT / 'manifest.json'
        manifest = driver.read(path)
        manifest.update(model_attempt_limit=4, scope='one original follow-up after explicit history scope references')
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
    args = parser.parse_args()
    prepare() if args.command == 'prepare' else execute()
