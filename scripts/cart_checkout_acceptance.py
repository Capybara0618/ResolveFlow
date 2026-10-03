"""Read and replay browser-owned synthetic multi-item purchases; preserve all original rows.

Snapshot precedes deployment. No case/refund/model calls and no new purchase creation.
Business POSTs replay original terminal payments and assert paid cancellation is denied;
keys/baselines remain local. No second buyer is seeded; foreign composite reads use the
trusted internal boundary, while public buyer isolation is covered by Java API tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

import reviewer_demo as demo
from multiline_money_acceptance import baseline
from resolveflow.contracts._schemaio import component_validator
from resolveflow.runtime.db import Database

ROOT = Path(__file__).resolve().parents[1]


def verify(settings: demo.Settings, database: Database, before: dict, samples: list) -> dict:
    buyer = demo.login(settings, 'demo-buyer', 'demo-pass-4001')
    trusted_case = demo.mint_service_token('case-service', scope='commerce:checkout')
    checks = []

    def check(label, path, expected=200, *, token=buyer, body=None, headers=None, internal=False):
        status, data = demo.http('POST' if body is not None else 'GET',
                                 (settings.commerce_url if internal else settings.gateway_url) + path,
                                 token=token, body=body, headers=headers)
        checks.append({'check': label, 'status': status, 'expected': expected, 'passed': status == expected})
        assert status == expected, (label, status)
        return data

    def schema(name, value, owner='case'):
        v = component_validator(owner, name, 'contracts/core')
        assert v.accepts(value), v.error_messages(value)

    check('anonymous cart denied', '/api/v1/shop/cart', 401, token=None)
    for user, password in [('demo-admin', 'demo-pass-1100'), ('demo-customer', 'demo-pass-1001')]:
        check(user + ' cannot read buyer cart', '/api/v1/shop/cart', 403, token=demo.login(settings, user, password))
    other_cart = check('foreign composite cart is independent',
                       '/internal/v1/shop/cart/M-1001?customer_id=C-1001', token=trusted_case, internal=True)
    assert not other_cart['items']
    cart = check('current buyer cart survives both store checkouts', '/api/v1/shop/cart')
    schema('Cart', cart)
    assert [(s['store_id'], [i['sku_id'] for i in s['items']]) for s in cart['stores']] == [
        ('M-1001', ['SKU-1003-GRAY']), ('M-1002', [])]
    assert cart['stores'][0]['items'][0]['quantity'] == 1
    assert cart['stores'][0]['items'][0]['total_amount'] == 8900
    agent = demo.mint_service_token('agent-service', scope='commerce:checkout')
    check('agent even with checkout scope cannot read cart',
          '/internal/v1/shop/cart/M-1001?customer_id=C-B3001-M1001', 403, token=agent, internal=True)
    outcomes = []
    assert len(samples) == 2
    for sample in samples:
        draft = str(uuid.UUID(sample['url'].split('#/shop/drafts/')[1]))
        p = check('own multi-item purchase', '/api/v1/shop/purchases/draft%3A' + draft)
        schema('CheckoutPurchase', p)
        assert p['status'] == 'PAID' and p['refund_status'] == 'NONE' and len(p['lines']) == 2
        expected = {'M-1001': (72700, [('SKU-1001-BLACK', 1, 32900), ('SKU-1002-WHITE', 2, 39800)]),
                    'M-1002': (21800, [('SKU-2001-CREAM', 1, 12900), ('SKU-2002-SILVER', 1, 8900)])}[p['store_id']]
        assert p['total_amount'] == expected[0]
        assert [(l['sku'], l['quantity'], l['line_amount']) for l in p['lines']] == expected[1]
        order = str(uuid.UUID(p['order_id']))
        attempt = str(uuid.UUID(p['payment']['attempt_id']))
        rows = demo.mysql_rows(f"SELECT kind,line_count,total_amount,status FROM checkout_draft WHERE draft_id='{draft}'",
                               settings, database='commerce_db')
        assert rows == [['MULTI', '2', str(expected[0]), 'PAID']]
        line_ids = [l['line_id'] for l in p['lines']]
        assert len(set(line_ids)) == 2
        ledger = demo.mysql_rows(f"SELECT paid_amount,refunded_amount,reserved_refund_amount,version FROM payment_ledger WHERE order_id='{order}'",
                                 settings, database='commerce_db')
        assert ledger == [[str(expected[0]), '0', '0', '1']]
        mapping = demo.mysql_rows(f"SELECT sku_id,line_id FROM checkout_payment_line WHERE attempt_id='{attempt}' ORDER BY sku_id",
                                  settings, database='commerce_db')
        assert mapping == [[l['sku'], l['line_id']] for l in p['lines']]
        original = check('all published lines available to original order API', '/api/v1/orders/' + order)
        assert {l['line_id'] for l in original['items']} == set(line_ids)
        checkout = check('original successful payment lookup', f'/api/v1/shop/drafts/{draft}/payment')['payment']
        schema('CheckoutPayment', checkout)
        keys = demo.mysql_rows(f"SELECT idempotency_key FROM checkout_payment_attempt WHERE attempt_id='{attempt}'",
                               settings, database='commerce_db')
        replay = check('terminal original payment replay', f'/api/v1/shop/drafts/{draft}/payment',
                       body={}, headers={'Idempotency-Key': keys[0][0]})
        assert replay == checkout
        for line in line_ids:
            context = check('line has own amount and total order ledger', '/internal/v1/order-lines/' + line + '/context',
                            token=demo.mint_service_token('case-service', scope='commerce:read'), internal=True)
            schema('LineContext', context, 'commerce')
            assert context['order_paid_amount'] == expected[0] and context['line_refund_state'] == 'FREE'
            slot = demo.mysql_rows(f"SELECT state,operation_id,version FROM line_refund WHERE line_id='{line}'",
                                   settings, database='commerce_db')
            assert slot == [['FREE', 'NULL', '1']]
        foreign = f'?merchant_id={p["store_id"]}&customer_id=C-1001'
        check('foreign composite cannot read multi-item purchase',
              '/internal/v1/shop/purchases/draft%3A' + draft + foreign, 404, token=trusted_case, internal=True)
        check('foreign composite cannot read payment', f'/internal/v1/shop/drafts/{draft}/payment' + foreign,
              404, token=trusted_case, internal=True)
        check('paid multi-item purchase cannot be cancelled', f'/api/v1/shop/drafts/{draft}/cancel', 409, body={})
        outcomes.append({'draft_id': draft, 'order_id': order, 'store_id': p['store_id'], 'total_amount': expected[0],
                         'status': p['status'], 'line_ids': line_ids, 'all_slots_free': True})
    assert {o['store_id'] for o in outcomes} == {'M-1001', 'M-1002'}
    after = baseline(settings, database)
    preserved = {}

    def canonical(values):
        return sorted(values, key=lambda value: json.dumps(value, sort_keys=True))

    for name, rows in before.items():
        ids = {r['run_id'] if isinstance(r, dict) else r[0] for r in rows}
        current = [r for r in after[name] if (r['run_id'] if isinstance(r, dict) else r[0]) in ids]
        assert canonical(rows) == canonical(current), 'Original rows changed: ' + name
        preserved[name] = {'rows': len(rows), 'unchanged': True,
                           'sha256': hashlib.sha256(json.dumps(canonical(rows)).encode()).hexdigest()}
    for group in ['cases', 'runs', 'run_spend', 'accounts', 'operations', 'authorizations', 'policies']:
        assert len(after[group]) == len(before[group])
    for group, count in [('orders', 2), ('payments', 2), ('drafts', 2), ('line_slots', 4)]:
        assert len(after[group]) == len(before[group]) + count
    return {'date': '2026-10-03', 'synthetic': True, 'model_calls': 0, 'checks': checks,
            'samples': outcomes, 'protected_originals': preserved, 'new_paid_orders': 2, 'new_lines': 4,
            'new_drafts': 2, 'new_refund_operations': 0, 'remaining_cart': 'M-1001 mouse quantity 1; M-1002 empty',
            'unknown_and_faults': 'isolated real MySQL tests only; no faults injected into preserved demo'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'tmp/cart-before.json')
    parser.add_argument('--samples', type=Path, default=ROOT / 'reports/cart-checkout/samples.json')
    parser.add_argument('--report', type=Path, default=ROOT / 'reports/cart-checkout/verification.json')
    args = parser.parse_args()
    settings = demo.Settings()
    demo.guard(settings)
    database = Database(settings.agent_dsn)
    try:
        report = verify(settings, database, json.loads(args.baseline.read_text(encoding='utf-8')),
                        json.loads(args.samples.read_text(encoding='utf-8'))['samples'])
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
        print(f"{len(report['checks'])} HTTP checks passed; originals unchanged; two multi-item paid orders; model calls 0")
    finally:
        database.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
