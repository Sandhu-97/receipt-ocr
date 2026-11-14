import os

os.environ.setdefault("FIREBASE_API_KEY", "test-key")

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


class _FakeMessage:
    content = '{"receipt_number": "42"}'


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]


class _FakeCompletions:
    def create(self, **_kwargs) -> _FakeResponse:
        return _FakeResponse()


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeOpenAI:
    def __init__(self, **_kwargs) -> None:
        self.chat = _FakeChat()


def _allow_auth() -> None:
    main.app.dependency_overrides[main.require_user] = lambda: "test-user"


def setup_function() -> None:
    main.app.dependency_overrides.clear()


def test_rejects_a_missing_token() -> None:
    response = client.post(
        "/extract", json={"imageBase64": "aGk=", "mediaType": "image/jpeg"}
    )
    assert response.status_code == 401


def test_rejects_an_unsupported_image_type() -> None:
    _allow_auth()
    response = client.post(
        "/extract", json={"imageBase64": "aGk=", "mediaType": "image/heic"}
    )
    assert response.status_code == 415


def test_returns_the_model_summary(monkeypatch) -> None:
    _allow_auth()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(main, "OpenAI", _FakeOpenAI)

    response = client.post(
        "/extract", json={"imageBase64": "aGk=", "mediaType": "image/jpeg"}
    )

    assert response.status_code == 200
    assert response.json() == {"summary": '{"receipt_number": "42"}'}
