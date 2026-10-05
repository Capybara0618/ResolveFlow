"""One 429 transmission is recoverable; the transport itself never retries."""

import datetime as dt
from email.utils import format_datetime

import pytest
from resolveflow.harness.live_model import HttpResponse, ModelRefusedError, ModelUnavailableError

from tests.unit.test_live_model_client import Recorder, client, messages


def test_429_is_transient_and_still_records_exactly_one_attempt():
    recorder = Recorder(HttpResponse(429, b"rate limited"))
    live = client(recorder)
    with pytest.raises(ModelUnavailableError) as error:
        live.decide(system="", messages=messages(), max_output_tokens=256)
    assert error.value.retry_after_seconds == 5
    assert live.calls == len(recorder.calls) == len(live.requests) == 1
    assert live.requests[0]["status"] == 429


@pytest.mark.parametrize("header,expected", [
    ("3", 3), ("0", 1), ("-1", 5), ("nan", 5), ("inf", 5), ("broken", 5), ("999999999", 86400),
])
def test_retry_after_is_bounded_and_invalid_values_use_safe_default(header, expected):
    live = client(Recorder(HttpResponse(429, b"", headers={"retry-after": header})))
    with pytest.raises(ModelUnavailableError) as error:
        live.decide(system="", messages=messages(), max_output_tokens=256)
    assert error.value.retry_after_seconds == expected


def test_http_date_retry_after_is_supported():
    later = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=35)
    live = client(Recorder(HttpResponse(429, b"", headers={"Retry-After": format_datetime(later, usegmt=True)})))
    with pytest.raises(ModelUnavailableError) as error:
        live.decide(system="", messages=messages(), max_output_tokens=256)
    assert 33 <= error.value.retry_after_seconds <= 35


@pytest.mark.parametrize("status", [400, 401, 403, 402])
def test_bad_request_auth_and_balance_errors_are_not_retried(status):
    live = client(Recorder(HttpResponse(status, b"request refused")))
    with pytest.raises(ModelRefusedError):
        live.decide(system="", messages=messages(), max_output_tokens=256)
    assert live.calls == 1
