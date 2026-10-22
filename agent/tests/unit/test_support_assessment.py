"""Policy conditions do not require order reads; individual assessments do."""

import pytest

from resolveflow.support.completion import CompletionError, check_completion
from resolveflow.support.protocol import AnswerParts
from resolveflow.support.tasks import render_answer
from tests.unit.test_support_tasks import task


def outcome(mode):
    return render_answer(AnswerParts.model_validate({
        'kind': 'ANSWER_PARTS', 'tasks': [task('refund', 'ELIGIBILITY')],
        'parts': [{'task_id': 'refund', 'status': 'ANSWERED', 'text': '按政策核验。',
                   'assessment': mode, 'citations': ['P1', 'O1']}],
    }), [])


def test_general_conditions_need_policy_without_requiring_an_order_read():
    answer = outcome('CONDITIONS')
    check_completion(answer, answer.tasks, {'P1': {'source_type': 'POLICY'}}, [])
    assert answer.tasks[0].assessment == 'CONDITIONS'


def test_case_assessment_rejects_policy_only_and_accepts_order_with_policy():
    answer = outcome('CASE_ASSESSMENT')
    citations = {'P1': {'source_type': 'POLICY'}}
    with pytest.raises(CompletionError) as error:
        check_completion(answer, answer.tasks, citations, [])
    assert error.value.gaps == [{'task_id': 'refund', 'code': 'SOURCE_REQUIRED',
                                 'tool_name': 'get_order_context'}]
    check_completion(answer, answer.tasks, {**citations, 'O1': {'source_type': 'ORDER'}}, [])


def test_order_elsewhere_in_the_answer_does_not_support_this_assessment():
    answer = outcome('CASE_ASSESSMENT')
    answer.tasks[0].evidence_refs = ['P1']
    with pytest.raises(CompletionError):
        check_completion(answer, answer.tasks, {
            'P1': {'source_type': 'POLICY'}, 'O1': {'source_type': 'ORDER'}}, [])
