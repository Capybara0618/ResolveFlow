import pytest
from fastapi.testclient import TestClient

from resolveflow.api.app import create_app
from resolveflow.api.identity import mint_service_token
from tests.unit.test_support_agent import request

SECRET = "support-test-only-secret-at-least-16"


class Runtime:
    def __init__(self):
        self.calls = []

    def run(self, context, token):
        self.calls.append((context, token))
        return {
            "run_id": context.run_id,
            "conversation_id": context.conversation_id,
            "input_version": context.input_version,
            "status": "FAILED",
            "reason": "MOCK_TEST",
            "mode": "mock",
            "spend": {},
            "answer": None,
        }


def test_consultation_route_requires_its_scope_and_exact_case_dispatch_subjects(tmp_path):
    runtime = Runtime()
    app = create_app(
        provider_db=tmp_path / "provider.db",
        delivery_loop=False,
        worker_loop=False,
        migrate=False,
        jwt_secret=SECRET,
        support_runtime=runtime,
    )
    body = {**request().model_dump(mode="json"), "tool_token": "per-run-read-token"}

    def headers(scope="support:run", merchant="M-A", subject="case-service"):
        token = mint_service_token(subject, SECRET, scope=scope, merchant_id=merchant, buyer_id="C-A")
        return {"Authorization": "Bearer " + token}

    with TestClient(app) as client:
        assert client.post("/internal/v1/support-runs", json=body).status_code == 401
        for header in [headers("run:dispatch"), headers(merchant="M-B"), headers(subject="agent-service")]:
            assert client.post("/internal/v1/support-runs", json=body, headers=header).status_code == 403
        assert not runtime.calls
        result = client.post("/internal/v1/support-runs", json=body, headers=headers())
        assert result.status_code == 200 and result.json()["mode"] == "mock"
        assert runtime.calls[0][1] == "per-run-read-token"
        assert "tool_token" not in runtime.calls[0][0].model_dump()
        assert (
            client.post("/internal/v1/support-runs", json={**body, "case_id": "fake"}, headers=headers()).status_code
            == 422
        )


@pytest.mark.parametrize("architecture", ["staged-v1", "orchestrated-v1"])
def test_default_runtime_receives_app_encoder_pool_but_separate_run_state(monkeypatch, tmp_path, architecture):
    from types import SimpleNamespace

    from resolveflow.runtime.factory import DeploymentConfig

    instances = []

    class DefaultRuntime(Runtime):
        def __init__(self, database, config, *, embeddings, architecture):
            super().__init__()
            self.embeddings = embeddings
            self.architecture = architecture
            instances.append(self)

    monkeypatch.setattr("resolveflow.support.api.SupportRuntime", DefaultRuntime)
    monkeypatch.setattr(DeploymentConfig, "from_environ", lambda: DeploymentConfig(mode="mock"))
    monkeypatch.setenv("RESOLVEFLOW_SUPPORT_ARCHITECTURE", architecture)
    app = create_app(
        provider_db=tmp_path / "provider.db",
        delivery_loop=False,
        worker_loop=False,
        migrate=False,
        jwt_secret=SECRET,
        run_store=SimpleNamespace(database=object()),
    )
    token = mint_service_token("case-service", SECRET, scope="support:run", merchant_id="M-A", buyer_id="C-A")
    body = {**request().model_dump(mode="json"), "tool_token": "per-run-read-token"}
    with TestClient(app) as client:
        assert client.get('/health').json()['support_architecture'] == architecture
        monkeypatch.setenv("RESOLVEFLOW_SUPPORT_ARCHITECTURE", "single")
        for _ in range(2):
            assert (
                client.post(
                    "/internal/v1/support-runs", json=body, headers={"Authorization": "Bearer " + token}
                ).status_code
                == 200
            )
        assert len(instances) == 2 and instances[0] is not instances[1]
        assert instances[0].embeddings is instances[1].embeddings is app.state.support_embeddings
        assert all(instance.architecture == architecture for instance in instances)
        assert len(instances[0].calls) == len(instances[1].calls) == 1


def test_unknown_support_architecture_fails_at_startup(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setenv('RESOLVEFLOW_SUPPORT_ARCHITECTURE', 'typo')
    app = create_app(provider_db=tmp_path / 'provider.db', delivery_loop=False, worker_loop=False,
                     migrate=False, jwt_secret=SECRET)
    with pytest.raises(ValueError, match='support architecture'), TestClient(app):
        pass
