"""One shared usage ledger with immutable per-experiment limits and process-safe reservations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from resolveflow.support.protocol import SupportFailure

from scripts.customer_rag_live_v2 import persist
from scripts.evaluation.models import live_guard


def read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if type(value.get('used')) is not int or value['used'] < 0:
        raise ValueError('invalid shared usage ledger')
    return value


class BudgetSession:
    """The parent owns the existing global lock; child reservations acquire a separate short mutex."""

    def __init__(self, ledger, session_id, plan_hash, *, expected_start, limits, total):
        if (type(expected_start) is not int or expected_start < 0 or type(total) is not int or total <= 0
                or not limits or any(type(n) is not int or n < 0 for n in limits.values())
                or sum(limits.values()) != total or not session_id):
            raise ValueError('invalid explicit session limits')
        self.ledger, self.session_id = Path(ledger), session_id
        self.plan_hash, self.start, self.limits, self.total = plan_hash, expected_start, dict(limits), total
        self.token = secrets.token_hex(32)
        self.guard = None

    def __enter__(self):
        self.guard = live_guard(self.ledger)
        self.guard.__enter__()
        try:
            with live_guard(self.ledger.with_name(self.ledger.name + '.hctx-mutex')):
                value = read(self.ledger)
                sessions = value.setdefault('hctx_sessions', {})
                prior = sessions.get(self.session_id)
                fixed = {'plan_sha256': self.plan_hash, 'start': self.start, 'limits': self.limits, 'total': self.total}
                if prior is not None:
                    if any(prior.get(k) != v for k, v in fixed.items()):
                        raise ValueError('session immutable limits/plan/start differ')
                    if value['used'] != self.start + sum(prior['used_by_phase'].values()):
                        raise ValueError('shared ledger start or unrelated usage differs')
                else:
                    if value['used'] != self.start:
                        raise ValueError('shared ledger start differs')
                    prior = {**fixed, 'used_by_phase': dict.fromkeys(self.limits, 0)}
                prior.update(owner_pid=os.getpid(), owner_hash=hashlib.sha256(self.token.encode()).hexdigest(),
                             owner_active=True)
                sessions[self.session_id] = prior
                persist(self.ledger, value)
            return self
        except BaseException:
            self.guard.__exit__(None, None, None)
            self.guard = None
            raise

    def __exit__(self, *args):
        try:
            with live_guard(self.ledger.with_name(self.ledger.name + '.hctx-mutex')):
                value = read(self.ledger)
                session = value.get('hctx_sessions', {}).get(self.session_id)
                if session and session.get('owner_pid') == os.getpid():
                    session['owner_active'] = False
                    persist(self.ledger, value)
        finally:
            if self.guard is not None:
                self.guard.__exit__(*args)


def reserve(ledger, session_id, owner_token, phase):
    """Conservatively count before sending; a lost unsent reservation is never refunded automatically."""
    ledger = Path(ledger)
    with live_guard(ledger.with_name(ledger.name + '.hctx-mutex')):
        value = read(ledger)
        session = value.get('hctx_sessions', {}).get(session_id)
        lock = ledger.with_name(ledger.name + '.lock')
        if not session or not session.get('owner_active') or not lock.exists():
            raise ValueError('no active owner for this budget session')
        if (lock.read_text(encoding='utf-8') != str(session['owner_pid'])
                or not hmac.compare_digest(session['owner_hash'], hashlib.sha256(owner_token.encode()).hexdigest())):
            raise ValueError('budget owner differs')
        counts = session['used_by_phase']
        if (phase not in counts or any(type(n) is not int or n < 0 for n in counts.values())
                or value['used'] != session['start'] + sum(counts.values())):
            raise ValueError('session phase/accounting mismatch')
        if sum(counts.values()) >= session['total'] or counts[phase] >= session['limits'][phase]:
            raise SupportFailure('EVALUATION_ALLOWANCE_EXHAUSTED')
        counts[phase] += 1
        value['used'] += 1
        persist(ledger, value)
        return {'global_used': value['used'], 'phase_used': counts[phase], 'session_used': sum(counts.values())}
