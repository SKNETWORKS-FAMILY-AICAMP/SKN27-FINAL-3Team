from app.services.auth_error_contract import (
    AUTH_ERROR_CONTRACT_VERSION,
    build_auth_error,
    build_www_authenticate_header,
    is_valid_mock_bearer_header,
    list_auth_error_contracts,
)


def test_auth_error_contract_lists_jwt_failure_envelopes():
    contracts = list_auth_error_contracts()

    assert {"auth_required", "token_invalid", "token_expired", "forbidden"} <= set(contracts)
    assert contracts["auth_required"]["contract_version"] == AUTH_ERROR_CONTRACT_VERSION
    assert contracts["auth_required"]["type"] == "auth"
    assert contracts["auth_required"]["status"] == 401
    assert contracts["auth_required"]["required_action"] == "login"
    assert contracts["forbidden"]["status"] == 403
    assert contracts["forbidden"]["auth"]["reason"] == "permission_denied"


def test_mock_bearer_header_accepts_any_non_empty_bearer_token():
    valid, error = is_valid_mock_bearer_header("Bearer dev-mock-token")

    assert valid
    assert error is None


def test_mock_bearer_header_rejects_missing_malformed_and_expired_tokens():
    missing_valid, missing_error = is_valid_mock_bearer_header(None)
    malformed_valid, malformed_error = is_valid_mock_bearer_header("Token dev-mock-token")
    expired_valid, expired_error = is_valid_mock_bearer_header("Bearer expired")

    assert not missing_valid
    assert missing_error == build_auth_error("auth_required")
    assert not malformed_valid
    assert malformed_error["error"]["code"] == "token_invalid"
    assert malformed_error["error"]["auth"]["reason"] == "malformed_authorization_header"
    assert not expired_valid
    assert expired_error == build_auth_error("token_expired")


def test_auth_error_contract_builds_www_authenticate_header():
    error = build_auth_error("token_expired")

    assert (
        build_www_authenticate_header(error)
        == 'Bearer error="token_expired", error_description="expired_token"'
    )
