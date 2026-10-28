"""Explicit positive gate fixtures for tests of evidence, grounding and recovery.

These helpers ASSUME the scripted goal is a preparation request. They do not assess language
and must not be used by semantic-intent regressions or any live/recorded evaluation driver.
Old saved decisions remain unchanged; inserted checks are synthetic test preconditions.
"""

from copy import deepcopy

from pydantic import ValidationError

from resolveflow.support.orchestration import TurnPlan


def approved_check(focus):
    return {'kind': 'CHECK_REQUEST', 'assessments': [
        {'task_id': f['id'], 'purpose': f['goal'], 'quote': f['operation_request'],
         'reason': '本结构测试显式假定买家要求准备，语言语义由独立测试覆盖。'}
        for f in focus if f['goal'] != 'EXPLAIN']}


def checked_script(script):
    result = []
    for index, raw in enumerate(script):
        decision = deepcopy(raw)
        result.append(decision)
        if index + 1 < len(script) and script[index + 1].get('kind') == 'CHECK_REQUEST':
            continue
        if decision.get('kind') == 'TURN_UNDERSTANDING':
            try:
                TurnPlan.model_validate(decision)
            except ValidationError:
                continue  # An intentionally invalid proposal must repair before reaching the gate.
            check = approved_check(decision['focus'])
        elif decision.get('kind') == 'REVIEW_GOAL':
            check = approved_check([{'id': decision['task_id'], 'goal': decision['goal'],
                                     'operation_request': decision.get('operation_request')}])
        else:
            continue
        if check['assessments']:
            result.append(check)
    return result


def approve_requests(flow, meaning):
    pending = flow.pending_requests(meaning, {})
    if pending:
        flow.check_requests(approved_check([{'id': item['task_id'], 'goal': flow.goals[item['task_id']],
                            'operation_request': item['quote']} for item in pending]), meaning, {})
