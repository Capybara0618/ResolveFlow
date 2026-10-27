# Saved synthetic regression fixtures

These small records preserve the model decisions, synthetic business inputs and tool responses used by the Agent regression tests. They are test inputs, not new model generations or evaluation results.

`manifest.json` records the original local report digest and the extracted fixture digest. Historical run metrics, full model request packets, usage journals and database exports remain in the local development archive. Tests retain their original assertions and exercise the same accepted/rejected decisions; only fixture paths and the test-only saved-tool adapter changed.

No model credentials are required. Run the ordinary Agent unit suite to verify these fixtures.
