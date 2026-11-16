import os
from types import SimpleNamespace

os.environ.setdefault("FIREBASE_API_KEY", "test-key")

import main
import receipt_precheck
from fastapi.testclient import TestClient
import pytest

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
    with main._user_requests_lock:
        main._user_requests.clear()


def test_rejects_a_missing_token() -> None:
    response = client.post(
        "/extract", json={"imageBase64": "aGk=", "mediaType": "image/jpeg"}
    )
    assert response.status_code == 401


def test_rejects_a_non_jwt_token_without_calling_google(monkeypatch) -> None:
    def no_lookup(*_args, **_kwargs):
        pytest.fail("Firebase lookup must not be called")

    monkeypatch.setattr(main.httpx, "AsyncClient", no_lookup)

    response = client.post(
        "/extract",
        json={"imageBase64": "aGk=", "mediaType": "image/jpeg"},
        headers={"Authorization": "Bearer junk"},
    )

    assert response.status_code == 401


def test_docs_and_openapi_are_not_exposed() -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


@pytest.mark.parametrize("origin", main.ALLOWED_ORIGINS)
def test_cors_allows_configured_web_origins(origin: str) -> None:
    allowed = client.options(
        "/extract",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == origin


def test_cors_rejects_other_web_origins() -> None:
    denied = client.options(
        "/extract",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_rejects_an_unsupported_image_type() -> None:
    _allow_auth()
    response = client.post(
        "/extract", json={"imageBase64": "aGk=", "mediaType": "image/heic"}
    )
    assert response.status_code == 415


def test_limits_extraction_requests_per_authenticated_user() -> None:
    _allow_auth()
    payload = {"imageBase64": "", "mediaType": "image/heic"}

    for _ in range(main.USER_REQUESTS_PER_MINUTE):
        assert client.post("/extract", json=payload).status_code == 415

    limited = client.post("/extract", json=payload)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0


def test_returns_the_model_summary(monkeypatch) -> None:
    _allow_auth()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(main, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(main, "is_receipt_image", lambda _image: True)

    response = client.post(
        "/extract", json={"imageBase64": "aGk=", "mediaType": "image/jpeg"}
    )

    assert response.status_code == 200
    assert response.json() == {"summary": '{"receipt_number": "42"}'}


def test_rejects_an_unconfirmed_receipt_before_calling_deepseek(monkeypatch) -> None:
    _allow_auth()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(main, "is_receipt_image", lambda _image: False)
    monkeypatch.setattr(
        main, "OpenAI", lambda **_kwargs: pytest.fail("DeepSeek must not be called")
    )

    response = client.post(
        "/extract", json={"imageBase64": "aGk=", "mediaType": "image/jpeg"}
    )

    assert response.status_code == 422


def test_returns_503_when_tesseract_is_unavailable(monkeypatch) -> None:
    _allow_auth()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def missing_tesseract(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(receipt_precheck.subprocess, "run", missing_tesseract)

    response = client.post(
        "/extract", json={"imageBase64": "aGk=", "mediaType": "image/jpeg"}
    )

    assert response.status_code == 503


@pytest.mark.parametrize(
    "text",
    [
        "GOOD RECEIPT VOUCHER",
        "GOOD DELIVERY VOUCHER",
        "COLD STORAGE",
        "COLD STORE",
        "GOOD RECEIPT V0UCH3R",
    ],
)
def test_receipt_precheck_accepts_any_single_marker(
    monkeypatch, capsys, text: str
) -> None:
    monkeypatch.setattr(
        receipt_precheck.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=text.encode()
        ),
    )

    assert receipt_precheck.is_receipt_image(b"image-bytes")
    assert "score=" in capsys.readouterr().out


def test_receipt_precheck_rejects_text_without_any_marker(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        receipt_precheck.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=b"Potato delivery"
        ),
    )

    assert not receipt_precheck.is_receipt_image(b"image-bytes")
    assert capsys.readouterr().out.count("score=") == 4


def test_receipt_precheck_rejects_more_than_two_ocr_errors() -> None:
    assert receipt_precheck._best_marker_distance(
        "goodreceiptvxxxher", "good receipt voucher"
    ) > receipt_precheck.MAX_MARKER_EDITS


def test_best_marker_distance_scores_normalized_text() -> None:
    assert (
        receipt_precheck._best_marker_distance(
            "GOOD RECEIPT V0UCH3R", "good receipt voucher"
        )
        == 2
    )
