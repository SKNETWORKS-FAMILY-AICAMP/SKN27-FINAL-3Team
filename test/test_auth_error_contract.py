from app.services.auth_error_contract import (
    AUTH_ERROR_CONTRACT_VERSION,
    build_auth_error,
    build_www_authenticate_header,
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


def test_auth_error_contract_builds_www_authenticate_header():
    error = build_auth_error("token_expired")

    assert (
        build_www_authenticate_header(error)
        == 'Bearer error="token_expired", error_description="expired_token"'
    )
