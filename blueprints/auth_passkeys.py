from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, Request

from blueprints.auth_common import (
    _copy_default_tasks_after_login,
    _passkey_unavailable_response,
    _resolve_auth_limit_service,
    _user_id_from_session,
)
from blueprints.auth_support import dep, get_auth_limit_service_dependency


async def api_list_passkeys(request: Request):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return dep("jsonify")({"status": "fail", "error": "ログインが必要です"}, status_code=401)

    passkeys = await dep("run_blocking")(dep("list_passkeys_for_user"), user_id)
    return dep("jsonify")({"status": "success", "passkeys": passkeys})


async def api_delete_passkey(request: Request):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return dep("jsonify")({"status": "fail", "error": "ログインが必要です"}, status_code=401)

    data, error_response = await dep("require_json_dict")(request, status="fail")
    if error_response is not None:
        return error_response

    try:
        passkey_id = int(data.get("passkey_id"))
    except (TypeError, ValueError):
        return dep("jsonify")({"status": "fail", "error": "Passkeyが指定されていません"}, status_code=400)

    deleted = await dep("run_blocking")(dep("delete_passkey"), user_id, passkey_id)
    if not deleted:
        return dep("jsonify")({"status": "fail", "error": "Passkeyが見つかりません"}, status_code=404)

    return dep("jsonify")({"status": "success"})


async def api_passkey_register_options(request: Request):
    if (
        dep("generate_registration_options") is None
        or dep("options_to_json") is None
        or dep("AuthenticatorSelectionCriteria") is None
        or dep("ResidentKeyRequirement") is None
        or dep("UserVerificationRequirement") is None
        or dep("PublicKeyCredentialHint") is None
        or dep("PublicKeyCredentialDescriptor") is None
        or dep("base64url_to_bytes") is None
        or dep("bytes_to_base64url") is None
    ):
        return _passkey_unavailable_response()

    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return dep("jsonify")({"status": "fail", "error": "ログインが必要です"}, status_code=401)

    user = await dep("run_blocking")(dep("get_user_by_id"), user_id)
    if not user:
        return dep("jsonify")({"status": "fail", "error": "ユーザーが存在しません"}, status_code=404)

    existing_passkeys = await dep("run_blocking")(dep("list_passkeys_for_user"), user_id)
    exclude_credentials = [
        dep("PublicKeyCredentialDescriptor")(id=dep("base64url_to_bytes")(row["credential_id"]))
        for row in existing_passkeys
        if isinstance(row.get("credential_id"), str) and row["credential_id"]
    ]

    options = dep("generate_registration_options")(
        rp_id=dep("get_passkey_rp_id")(request),
        rp_name=dep("get_passkey_rp_name")(),
        user_name=user["email"],
        user_id=str(user_id).encode("utf-8"),
        user_display_name=(user.get("username") or user["email"]),
        authenticator_selection=dep("AuthenticatorSelectionCriteria")(
            resident_key=dep("ResidentKeyRequirement").REQUIRED,
            user_verification=dep("UserVerificationRequirement").REQUIRED,
        ),
        exclude_credentials=exclude_credentials,
        hints=[
            dep("PublicKeyCredentialHint").CLIENT_DEVICE,
            dep("PublicKeyCredentialHint").SECURITY_KEY,
            dep("PublicKeyCredentialHint").HYBRID,
        ],
    )
    dep("store_passkey_registration_ceremony")(
        request.session,
        dep("bytes_to_base64url")(options.challenge),
    )
    return dep("jsonify")(json.loads(dep("options_to_json")(options)))


async def api_passkey_register_verify(request: Request):
    if (
        dep("verify_registration_response") is None
        or dep("base64url_to_bytes") is None
        or dep("bytes_to_base64url") is None
    ):
        return _passkey_unavailable_response()

    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return dep("jsonify")({"status": "fail", "error": "ログインが必要です"}, status_code=401)

    ceremony = dep("get_passkey_registration_ceremony")(request.session)
    if ceremony is None:
        return dep("jsonify")({"status": "fail", "error": "Passkey登録を最初からやり直してください"}, status_code=400)
    if dep("passkey_ceremony_is_expired")(ceremony):
        dep("clear_passkey_session")(request.session)
        return dep("jsonify")(
            {
                "status": "fail",
                "error": (
                    f"Passkey登録の有効期限が切れています。"
                    f"{dep('PASSKEY_CHALLENGE_TTL_SECONDS') // 60}分以内に再試行してください"
                ),
            },
            status_code=400,
        )

    data, error_response = await dep("require_json_dict")(request, status="fail")
    if error_response is not None:
        return error_response

    credential = data.get("credential")
    label = data.get("label")
    if not isinstance(credential, dict):
        return dep("jsonify")({"status": "fail", "error": "Passkeyの応答が不正です"}, status_code=400)

    try:
        verified = dep("verify_registration_response")(
            credential=credential,
            expected_challenge=dep("base64url_to_bytes")(ceremony["challenge"]),
            expected_rp_id=dep("get_passkey_rp_id")(request),
            expected_origin=dep("get_passkey_origins")(request),
            require_user_verification=True,
        )
        passkey = await dep("run_blocking")(
            dep("create_passkey"),
            user_id,
            dep("bytes_to_base64url")(verified.credential_id),
            dep("bytes_to_base64url")(verified.credential_public_key),
            int(verified.sign_count),
            aaguid=verified.aaguid,
            credential_device_type=str(verified.credential_device_type.value),
            credential_backed_up=bool(verified.credential_backed_up),
            label=str(label) if isinstance(label, str) else None,
        )
    except Exception as exc:
        dep("logger").exception(
            "Passkey registration verification failed for user %s: %s: %s",
            user_id,
            type(exc).__name__,
            exc,
        )
        dep("clear_passkey_session")(request.session)
        return dep("jsonify")({"status": "fail", "error": "Passkeyの登録に失敗しました"}, status_code=400)

    dep("clear_passkey_session")(request.session)
    return dep("jsonify")({"status": "success", "passkey": passkey})


async def api_passkey_authenticate_options(
    request: Request,
    auth_limit_service: Any | None = Depends(get_auth_limit_service_dependency),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    if (
        dep("generate_authentication_options") is None
        or dep("options_to_json") is None
        or dep("UserVerificationRequirement") is None
        or dep("bytes_to_base64url") is None
    ):
        return _passkey_unavailable_response()

    allowed, limit_error = dep("consume_passkey_auth_options_limit")(
        request,
        service=resolved_auth_limit_service,
    )
    if not allowed:
        return dep("jsonify_rate_limited")(
            limit_error or "試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=dep("parse_retry_after_seconds")(
                limit_error,
                default=dep("DEFAULT_RETRY_AFTER_SECONDS"),
            ),
            status="fail",
        )

    options = dep("generate_authentication_options")(
        rp_id=dep("get_passkey_rp_id")(request),
        user_verification=dep("UserVerificationRequirement").REQUIRED,
    )
    dep("store_passkey_authentication_ceremony")(
        request.session,
        dep("bytes_to_base64url")(options.challenge),
    )
    return dep("jsonify")(json.loads(dep("options_to_json")(options)))


async def api_passkey_authenticate_verify(
    request: Request,
    auth_limit_service: Any | None = Depends(get_auth_limit_service_dependency),
):
    resolved_auth_limit_service = _resolve_auth_limit_service(request, auth_limit_service)
    if dep("verify_authentication_response") is None or dep("base64url_to_bytes") is None:
        return _passkey_unavailable_response()

    allowed, limit_error = dep("consume_passkey_auth_verify_limit")(
        request,
        service=resolved_auth_limit_service,
    )
    if not allowed:
        return dep("jsonify_rate_limited")(
            limit_error or "試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=dep("parse_retry_after_seconds")(
                limit_error,
                default=dep("DEFAULT_RETRY_AFTER_SECONDS"),
            ),
            status="fail",
        )

    ceremony = dep("get_passkey_authentication_ceremony")(request.session)
    if ceremony is None:
        return dep("jsonify")({"status": "fail", "error": "Passkey認証を最初からやり直してください"}, status_code=400)
    if dep("passkey_ceremony_is_expired")(ceremony):
        dep("clear_passkey_session")(request.session)
        return dep("jsonify")(
            {
                "status": "fail",
                "error": (
                    f"Passkey認証の有効期限が切れています。"
                    f"{dep('PASSKEY_CHALLENGE_TTL_SECONDS') // 60}分以内に再試行してください"
                ),
            },
            status_code=400,
        )

    data, error_response = await dep("require_json_dict")(request, status="fail")
    if error_response is not None:
        return error_response

    credential = data.get("credential")
    if not isinstance(credential, dict):
        return dep("jsonify")({"status": "fail", "error": "Passkeyの応答が不正です"}, status_code=400)

    credential_id = dep("get_credential_lookup_id")(credential)
    if not isinstance(credential_id, str) or not credential_id:
        return dep("jsonify")({"status": "fail", "error": "PasskeyのIDが不正です"}, status_code=400)

    passkey = await dep("run_blocking")(dep("get_passkey_by_credential_id"), credential_id)
    if not passkey:
        dep("clear_passkey_session")(request.session)
        return dep("jsonify")({"status": "fail", "error": "Passkey認証に失敗しました"}, status_code=400)

    try:
        verified = dep("verify_authentication_response")(
            credential=credential,
            expected_challenge=dep("base64url_to_bytes")(ceremony["challenge"]),
            expected_rp_id=dep("get_passkey_rp_id")(request),
            expected_origin=dep("get_passkey_origins")(request),
            credential_public_key=dep("base64url_to_bytes")(passkey["public_key"]),
            credential_current_sign_count=int(passkey["sign_count"] or 0),
            require_user_verification=True,
        )
    except Exception as exc:
        dep("logger").exception(
            "Passkey authentication verification failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        dep("clear_passkey_session")(request.session)
        return dep("jsonify")({"status": "fail", "error": "Passkey認証に失敗しました"}, status_code=400)

    user = await dep("run_blocking")(dep("get_user_by_id"), passkey["user_id"])
    if not user or not user.get("is_verified"):
        dep("clear_passkey_session")(request.session)
        return dep("jsonify")(
            {"status": "fail", "error": "ユーザーが存在しないか、認証されていません"},
            status_code=400,
        )

    dep("establish_authenticated_session")(request, int(passkey["user_id"]), user["email"])
    dep("clear_passkey_session")(request.session)

    try:
        await dep("run_blocking")(
            dep("update_passkey_usage"),
            int(passkey["id"]),
            int(verified.new_sign_count),
            credential_backed_up=bool(verified.credential_backed_up),
            credential_device_type=str(verified.credential_device_type.value),
        )
    except Exception:
        dep("logger").exception(
            "Passkey authentication: failed to update credential usage for passkey %s",
            passkey["id"],
        )

    await _copy_default_tasks_after_login(
        int(passkey["user_id"]),
        context="Passkey authentication",
    )

    return dep("jsonify")({"status": "success", "message": "Passkeyでログインしました"})
