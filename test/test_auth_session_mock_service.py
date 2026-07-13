from app.services.auth_session_mock_service import (
    create_guest_session,
    get_current_auth_subject,
)
from app.services import google_auth_service
from app.services.google_auth_service import create_google_login


def test_create_guest_session_separates_guest_and_chat_session_ids():
    payload = {"guest_id": "gst_existing", "session_id": "ses_guest_chat"}

    guest_session = create_guest_session(payload)

    assert guest_session["auth_state"] == "guest"
    assert guest_session["guest"]["guest_id"] == "gst_existing"
    assert guest_session["subject"]["subject_id"] == "guest:gst_existing"
    assert guest_session["subject"]["auth_session_id"] is None
    assert guest_session["session_binding"]["session_id"] == "ses_guest_chat"
    assert guest_session["merge_policy"]["auto_merge"] is False
    assert guest_session["rate_limit"]["policy_status"] == "review_required"


def test_auth_me_returns_authenticated_subject_for_valid_mock_bearer():
    status, payload = get_current_auth_subject(
        authorization_header="Bearer dev-mock-token",
        guest_id="gst_before_login",
        session_id="ses_after_login",
    )

    assert status == 200
    assert payload["auth_state"] == "authenticated"
    assert payload["subject"]["subject_id"] == "user:usr_mock"
    assert payload["subject"]["guest_id"] == "gst_before_login"
    assert payload["subject"]["auth_session_id"] == "auth_dev_mock"
    assert payload["auth_session"]["verification"] == "mock_bearer_shape_only"


def test_auth_me_returns_guest_or_anonymous_without_bearer():
    guest_status, guest_payload = get_current_auth_subject(
        authorization_header=None,
        guest_id="guest_from_header",
    )
    anon_status, anon_payload = get_current_auth_subject(
        authorization_header=None,
        guest_id=None,
    )

    assert guest_status == 200
    assert guest_payload["auth_state"] == "guest"
    assert guest_payload["guest"]["guest_id"] == "gst_guest_from_header"
    assert anon_status == 200
    assert anon_payload["auth_state"] == "anonymous"


def test_auth_me_reuses_auth_error_contract_for_invalid_bearer():
    status, payload = get_current_auth_subject(
        authorization_header="Bearer expired",
    )

    assert status == 401
    assert payload["error"]["contract_version"] == "auth_error.v1"
    assert payload["error"]["code"] == "token_expired"


def test_google_login_rejects_mock_profile_when_mock_google_auth_disabled(monkeypatch):
    monkeypatch.setenv("GOOGLE_AUTH_ALLOW_MOCK", "0")

    status, payload = create_google_login(
        {
            "provider": "google",
            "google_sub": "dev-google-subject",
            "email": "driver@example.com",
        }
    )

    assert status == 401
    assert payload["error"]["code"] == "token_invalid"
    assert payload["error"]["auth"]["reason"] == "google_identity_missing"


def test_google_login_issues_a_new_auth_session_for_each_login(monkeypatch):
    google_profile = {
        "sub": "google-user-123",
        "email": "driver@example.com",
        "display_name": "Driver",
        "picture": "",
        "aud": "test-client",
        "verification": "google_id_token_verified",
    }
    monkeypatch.setattr(
        google_auth_service,
        "_google_profile_from_payload",
        lambda _payload: google_profile,
    )

    first_status, first = create_google_login({"id_token": "first"})
    second_status, second = create_google_login({"id_token": "second"})

    assert first_status == 200
    assert second_status == 200
    assert first["subject"]["auth_session_id"] != second["subject"]["auth_session_id"]
