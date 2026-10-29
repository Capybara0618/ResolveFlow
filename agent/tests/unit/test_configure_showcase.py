import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "configure_showcase", Path(__file__).resolve().parents[3] / "scripts/configure_showcase.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_existing_merchant_content_is_never_adopted_as_our_own():
    with pytest.raises(ValueError, match="已有资料"):
        module.require_owned("店铺", {"version": 1, "introduction": "商家自己的介绍"}, None)


def test_resume_requires_exact_last_saved_content_and_version():
    saved = {"version": 2, "images": ["ours"]}
    module.require_owned("商品", saved.copy(), saved)
    with pytest.raises(ValueError, match="已有资料"):
        module.require_owned("商品", {"version": 3, "images": ["someone-else"]}, saved)


def test_only_empty_new_presentation_can_be_initialized():
    module.require_owned("商品", {"version": 0, "images": []}, None)
    with pytest.raises(ValueError, match="已有资料"):
        module.require_owned("商品", {"version": 0, "images": ["unexpected"]}, None)


def test_fixture_path_cannot_escape_asset_pack():
    with pytest.raises(ValueError):
        module.asset_path("../credentials.json")


def test_unknown_save_result_is_adopted_only_with_matching_fields_and_version():
    body = {"expected_version": 1, "images": ["ours"]}
    assert module.Configuration.matches({"version": 2, "images": ["ours"]}, body)
    assert not module.Configuration.matches({"version": 3, "images": ["ours"]}, body)
    assert not module.Configuration.matches({"version": 2, "images": ["other"]}, body)


def test_avatar_does_not_adopt_a_concurrent_profile_version(monkeypatch, tmp_path):
    photo = tmp_path / "avatar.jpg"
    photo.write_bytes(b"image")
    monkeypatch.setattr(module, "asset_path", lambda _: photo)
    work = object.__new__(module.Configuration)
    work.state = {"avatars": {}}
    work.current_profiles = {"buyer": {"version": 7}}

    class Response:
        def json(self):
            return {"version": 8}

    def request(method, path, username, **kwargs):
        if method == "GET":
            return Response()  # Another user action changed the profile after preflight.
        assert kwargs["data"]["expected_version"] == "7"
        raise ValueError("version conflict")

    work.request = request
    with pytest.raises(ValueError, match="version conflict"):
        work.avatar("buyer", "avatar.jpg")
    assert work.state["avatars"] == {}
