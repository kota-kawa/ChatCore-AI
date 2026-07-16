import logging
import os
import time

import requests
from dotenv import load_dotenv
from fastapi import APIRouter, Depends
from starlette.responses import RedirectResponse

try:
    from google_auth_oauthlib.flow import Flow
except ModuleNotFoundError:  # pragma: no cover - optional for test envs
    Flow = None

try:
    from google.auth.exceptions import GoogleAuthError
except ModuleNotFoundError:  # pragma: no cover - optional for test envs
    class GoogleAuthError(Exception):
        pass

try:
    from oauthlib.oauth2.rfc6749.errors import OAuth2Error
except ModuleNotFoundError:  # pragma: no cover - optional for test envs
    class OAuth2Error(Exception):
        pass

try:
    from webauthn import (
        generate_authentication_options,
        generate_registration_options,
        verify_authentication_response,
        verify_registration_response,
    )
    from webauthn.helpers import (
        base64url_to_bytes,
        bytes_to_base64url,
        options_to_json,
    )
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        PublicKeyCredentialHint,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )
except ModuleNotFoundError:  # pragma: no cover - optional for test envs
    generate_authentication_options = None
    generate_registration_options = None
    verify_authentication_response = None
    verify_registration_response = None
    options_to_json = None
    base64url_to_bytes = None
    bytes_to_base64url = None
    AuthenticatorSelectionCriteria = None
    PublicKeyCredentialDescriptor = None
    PublicKeyCredentialHint = None
    ResidentKeyRequirement = None
    UserVerificationRequirement = None

from blueprints.auth_account import (  # noqa: E402
    api_current_user,
    api_delete_user_account,
    login,
    logout,
    register_page,
)
from blueprints.auth_common import (  # noqa: E402
    _append_query_params,
    _build_absolute_url_from_reference,
    _clear_google_oauth_session,
    _clear_google_oauth_state,
    _clear_login_verification_session,
    _copy_default_tasks_after_login,
    _google_callback_redirect_target,
    _google_login_unavailable_response,
    _google_next_path,
    _passkey_unavailable_response,
    _redirect_to_login_after_google_failure,
    _resolve_auth_limit_service,
    _resolve_llm_daily_limit_service,
    _user_id_from_session,
)
from blueprints.auth_email import (  # noqa: E402
    api_send_email_code,
    api_send_login_code,
    api_verify_email_code,
    api_verify_login_code,
)
from blueprints.auth_google import (  # noqa: E402
    _build_google_authorization_response,
    _build_google_login_host_redirect,
    _clean_google_field,
    _fetch_google_user_info,
    _google_client_config,
    _validate_google_oauth_settings,
    google_callback,
    google_login,
)
from blueprints.auth_passkeys import (  # noqa: E402
    api_delete_passkey,
    api_list_passkeys,
    api_passkey_authenticate_options,
    api_passkey_authenticate_verify,
    api_passkey_register_options,
    api_passkey_register_verify,
)
from blueprints.verification import (  # noqa: E402
    api_send_verification_email,
    api_verify_registration_code,
)
from services.api_errors import DEFAULT_RETRY_AFTER_SECONDS, parse_retry_after_seconds  # noqa: E402
from services.async_utils import run_blocking  # noqa: E402
from services.auth_limits import (  # noqa: E402
    AuthLimitService,
    consume_auth_email_send_limits,
    consume_passkey_auth_options_limit,
    consume_passkey_auth_verify_limit,
    consume_verification_attempt_limit,
    get_auth_limit_service,
)
from services.auth_session import establish_authenticated_session  # noqa: E402
from services.csrf import require_csrf  # noqa: E402
from services.email_service import send_email  # noqa: E402
from services.llm_daily_limit import (  # noqa: E402
    LlmDailyLimitService,
    consume_auth_email_daily_quota,
    get_seconds_until_daily_reset,
    get_llm_daily_limit_service,
)
from services.passkeys import (  # noqa: E402
    PASSKEY_CHALLENGE_TTL_SECONDS,
    clear_passkey_session,
    create_passkey,
    delete_passkey,
    get_credential_lookup_id,
    get_passkey_authentication_ceremony,
    get_passkey_by_credential_id,
    get_passkey_origins,
    get_passkey_registration_ceremony,
    get_passkey_rp_id,
    get_passkey_rp_name,
    list_passkeys_for_user,
    passkey_ceremony_is_expired,
    store_passkey_authentication_ceremony,
    store_passkey_registration_ceremony,
    update_passkey_usage,
)
from services.request_models import AuthCodeRequest, EmailRequest  # noqa: E402
from services.runtime_config import is_production_env  # noqa: E402
from services.security import constant_time_compare, generate_verification_code  # noqa: E402
from services.users import (  # noqa: E402
    ACCOUNT_DELETE_CONFIRMATION_TEXT,
    GOOGLE_AUTH_PROVIDER,
    copy_default_tasks_for_user,
    create_user,
    delete_user_account,
    get_user_by_email,
    get_user_by_google_id,
    get_user_by_id,
    link_google_account,
    set_user_verified,
    update_user_profile_from_google_if_unset,
)
from services.web import (  # noqa: E402
    frontend_login_url,
    frontend_url,
    jsonify,
    jsonify_rate_limited,
    log_and_internal_server_error,
    redirect_to_frontend,
    require_json_dict,
    sanitize_next_path,
    set_session_permanent,
    url_for,
    validate_payload_model,
)

load_dotenv()

if not is_production_env():
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

GOOGLE_LOGIN_UNAVAILABLE_ERROR = "Googleログインを現在利用できません。"
PASSKEY_UNAVAILABLE_ERROR = "Passkeyログインを現在利用できません。"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

auth_bp = APIRouter(dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)

LOGIN_VERIFICATION_CODE_TTL_SECONDS = 300
LOGIN_VERIFICATION_CODE_MAX_ATTEMPTS = 5
GOOGLE_CODE_VERIFIER_SESSION_KEY = "google_oauth_code_verifier"
GOOGLE_NEXT_PATH_SESSION_KEY = "google_login_next_path"
AUTH_FAILURE_STATUS_CODE = 401

auth_bp.get("/register", name="auth.register_page")(register_page)
auth_bp.get("/api/current_user", name="auth.api_current_user")(api_current_user)
auth_bp.delete("/api/user/account", name="auth.api_delete_user_account")(api_delete_user_account)
auth_bp.get("/login", name="auth.login")(login)
auth_bp.post("/logout", name="auth.logout")(logout)
auth_bp.post("/api/auth/send_email_code", name="auth.api_send_email_code")(api_send_email_code)
auth_bp.post("/api/auth/verify_email_code", name="auth.api_verify_email_code")(api_verify_email_code)
auth_bp.get("/api/passkeys", name="auth.api_list_passkeys")(api_list_passkeys)
auth_bp.post("/api/passkeys/delete", name="auth.api_delete_passkey")(api_delete_passkey)
auth_bp.post("/api/passkeys/register/options", name="auth.api_passkey_register_options")(api_passkey_register_options)
auth_bp.post("/api/passkeys/register/verify", name="auth.api_passkey_register_verify")(api_passkey_register_verify)
auth_bp.post("/api/passkeys/authenticate/options", name="auth.api_passkey_authenticate_options")(api_passkey_authenticate_options)
auth_bp.post("/api/passkeys/authenticate/verify", name="auth.api_passkey_authenticate_verify")(api_passkey_authenticate_verify)
auth_bp.get("/google-login", name="auth.google_login")(google_login)
auth_bp.get("/google-callback", name="auth.google_callback")(google_callback)
auth_bp.post("/api/send_login_code", name="auth.api_send_login_code")(api_send_login_code)
auth_bp.post("/api/verify_login_code", name="auth.api_verify_login_code")(api_verify_login_code)

__all__ = [
    "ACCOUNT_DELETE_CONFIRMATION_TEXT",
    "AUTH_FAILURE_STATUS_CODE",
    "AuthCodeRequest",
    "AuthLimitService",
    "AuthenticatorSelectionCriteria",
    "DEFAULT_RETRY_AFTER_SECONDS",
    "EmailRequest",
    "Flow",
    "GOOGLE_AUTH_PROVIDER",
    "GOOGLE_CODE_VERIFIER_SESSION_KEY",
    "GOOGLE_LOGIN_UNAVAILABLE_ERROR",
    "GOOGLE_NEXT_PATH_SESSION_KEY",
    "GOOGLE_SCOPES",
    "GoogleAuthError",
    "LOGIN_VERIFICATION_CODE_MAX_ATTEMPTS",
    "LOGIN_VERIFICATION_CODE_TTL_SECONDS",
    "LlmDailyLimitService",
    "OAuth2Error",
    "PASSKEY_CHALLENGE_TTL_SECONDS",
    "PASSKEY_UNAVAILABLE_ERROR",
    "PublicKeyCredentialDescriptor",
    "PublicKeyCredentialHint",
    "RedirectResponse",
    "ResidentKeyRequirement",
    "UserVerificationRequirement",
    "_append_query_params",
    "_build_absolute_url_from_reference",
    "_build_google_authorization_response",
    "_build_google_login_host_redirect",
    "_clean_google_field",
    "_clear_google_oauth_session",
    "_clear_google_oauth_state",
    "_clear_login_verification_session",
    "_copy_default_tasks_after_login",
    "_fetch_google_user_info",
    "_google_callback_redirect_target",
    "_google_client_config",
    "_google_login_unavailable_response",
    "_google_next_path",
    "_passkey_unavailable_response",
    "_redirect_to_login_after_google_failure",
    "_resolve_auth_limit_service",
    "_resolve_llm_daily_limit_service",
    "_user_id_from_session",
    "_validate_google_oauth_settings",
    "api_current_user",
    "api_delete_passkey",
    "api_delete_user_account",
    "api_list_passkeys",
    "api_passkey_authenticate_options",
    "api_passkey_authenticate_verify",
    "api_passkey_register_options",
    "api_passkey_register_verify",
    "api_send_email_code",
    "api_send_login_code",
    "api_send_verification_email",
    "api_verify_email_code",
    "api_verify_login_code",
    "api_verify_registration_code",
    "auth_bp",
    "base64url_to_bytes",
    "bytes_to_base64url",
    "clear_passkey_session",
    "constant_time_compare",
    "consume_auth_email_daily_quota",
    "consume_auth_email_send_limits",
    "consume_passkey_auth_options_limit",
    "consume_passkey_auth_verify_limit",
    "consume_verification_attempt_limit",
    "copy_default_tasks_for_user",
    "create_passkey",
    "create_user",
    "delete_passkey",
    "delete_user_account",
    "establish_authenticated_session",
    "frontend_login_url",
    "frontend_url",
    "generate_authentication_options",
    "generate_registration_options",
    "generate_verification_code",
    "get_auth_limit_service",
    "get_credential_lookup_id",
    "get_llm_daily_limit_service",
    "get_passkey_authentication_ceremony",
    "get_passkey_by_credential_id",
    "get_passkey_origins",
    "get_passkey_registration_ceremony",
    "get_passkey_rp_id",
    "get_passkey_rp_name",
    "get_seconds_until_daily_reset",
    "get_user_by_email",
    "get_user_by_google_id",
    "get_user_by_id",
    "google_callback",
    "google_login",
    "is_production_env",
    "jsonify",
    "jsonify_rate_limited",
    "link_google_account",
    "list_passkeys_for_user",
    "log_and_internal_server_error",
    "logger",
    "login",
    "logout",
    "options_to_json",
    "os",
    "parse_retry_after_seconds",
    "passkey_ceremony_is_expired",
    "redirect_to_frontend",
    "register_page",
    "requests",
    "require_csrf",
    "require_json_dict",
    "run_blocking",
    "sanitize_next_path",
    "send_email",
    "set_session_permanent",
    "set_user_verified",
    "store_passkey_authentication_ceremony",
    "store_passkey_registration_ceremony",
    "time",
    "update_passkey_usage",
    "update_user_profile_from_google_if_unset",
    "url_for",
    "validate_payload_model",
    "verify_authentication_response",
    "verify_registration_response",
]
