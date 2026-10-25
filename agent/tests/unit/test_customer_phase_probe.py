"""The last two probes preserve actual inputs and accepted prefixes, never fabricated answers."""

from scripts import probe_customer_phase_closeout_v1 as driver


def test_points_use_exact_saved_context_and_distinct_new_runs_without_fabricated_history():
    selected = driver.cases()
    assert [(c["original_id"], c["original_turn"]) for c in selected] == [("F01", 4), ("F03", 2)]
    for case in selected:
        req, history = driver.prepare_turn(case, 0, [])
        assert req.context == case["saved_input"]["context"]
        assert req.run_id != case["saved_input"]["run_id"]
        assert req.input_version == case["saved_input"]["input_version"]
        assert history == req.context["history"]
        assert req.context["previous_customer_memory"]["conversation_id"] == req.conversation_id
    assert driver.ENVELOPE_START + driver.ENVELOPE_LIMIT == 2450
