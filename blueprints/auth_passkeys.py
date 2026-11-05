"""Passkey(WebAuthn)の API。登録済み Passkey の一覧・削除、登録(オプション生成と検証)、Passkey でのログイン(オプション生成と検証)を扱う。

WebAuthn の challenge(儀式)はセッションに短時間だけ保存し、検証後に必ず片付ける。
WebAuthn ライブラリが無い環境では 503 を返す。ルートへの結び付けは blueprints/auth.py が行う。

Passkey (WebAuthn) APIs: list and delete registered passkeys, register one (options and verification)
and sign in with one (options and verification).
The WebAuthn challenge (ceremony) is kept in the session only briefly and always cleared after verification.
Without the WebAuthn library these answer 503. Routes are bound in blueprints/auth.py.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, Request

from blueprints.auth_common import (
    _claim_guest_prompts_after_login,
    _copy_default_tasks_after_login,
    _passkey_unavailable_response,
    _resolve_auth_limit_service,
    _user_id_from_session,
)
from blueprints.auth_support import call_dependency, dep, get_auth_limit_service_dependency
from services.error_messages import ERROR_PASSKEY_USAGE_UPDATE_FAILED


# ログイン中ユーザーが登録した Passkey の一覧を返す。
# List the passkeys registered by the signed-in user.
async def api_list_passkeys(request: Request):
    user_id = _user_id_from_session(request.session)
    if user_id is None:
        return dep("jsonify")({"status": "fail", "error": "ログインが必要です"}, status_code=401)

    passkeys = await call_dependency("list_passkeys_for_user", user_id)
    return dep("jsonify")({"status": "success", "passkeys": passkeys})


# 指定した Passkey を、ログイン中ユーザー自身のものに限って削除する。
# Delete the given passkey, only if it belongs to the signed-in user.
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

    deleted = await call_dependency("delete_passkey", user_id, passkey_id)
    if not deleted:
        return dep("jsonify")({"status": "fail", "error": "Passkeyが見つかりません"}, status_code=404)

    return dep("jsonify")({"status": "success"})


# Passkey 登録用の WebAuthn オプションを作る。登録済みの認証器は exclude_credentials に入れて二重登録を防ぎ、challenge はセッションに保
# 存する。
# Create WebAuthn registration options; existing credentials go into exclude_credentials to prevent duplicates, and the challenge is
# saved in the session.
async def api_passkey_register_options(request: Request):
    # WebAuthn ライブラリが任意依存のため、必要な部品が揃わない環境では機能ごと無効として 503 を返す。
    # The WebAuthn library is optional; when any required piece is missing, answer 503 for the whole feature.
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

    user = await call_dependency("get_user_by_id", user_id)
    if not user:
        return dep("jsonify")({"status": "fail", "error": "ユーザーが存在しません"}, status_code=404)

    existing_passkeys = await call_dependency("list_passkeys_for_user", user_id)
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


# ブラウザが返した登録結果を、保存済みの challenge・RP ID・オリジンに対して検証し、成功したら Passkey を保存する。成否にかかわらずセッシ
# ョンの儀式は消す。
# Verify the browser's registration response against the stored challenge, RP ID and origins, then save the passkey; the session
# ceremony is cleared either way.
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
        passkey = await call_dependency(
            "create_passkey",
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


# Passkey ログイン用の WebAuthn オプションを作り、challenge をセッションに保存する。呼び出し回数は IP などで制限する。
# Create WebAuthn authentication options and save the challenge in the session; call frequency is rate-limited.
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


# ブラウザが返した認証結果を検証してログインを確立する。回数制限 → 儀式の有効期限 → 認証器の特定 → 署名検証 → 署名カウンタの更新の順に進
# む。
# Verify the browser's authentication response and establish the login: rate limit, ceremony expiry, credential lookup, signature check,
# then sign-count update.
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

    passkey = await call_dependency("get_passkey_by_credential_id", credential_id)
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

    user = await call_dependency("get_user_by_id", passkey["user_id"])
    if not user or not user.get("is_verified"):
        dep("clear_passkey_session")(request.session)
        return dep("jsonify")(
            {"status": "fail", "error": "ユーザーが存在しないか、認証されていません"},
            status_code=400,
        )

    # 署名カウンタは認証器のクローン検知に使うため、保存できないままログインさせない。
    # The sign count drives authenticator clone detection, so never sign in when it cannot be stored.
    try:
        await call_dependency(
            "update_passkey_usage",
            int(passkey["id"]),
            int(verified.new_sign_count),
            credential_backed_up=bool(verified.credential_backed_up),
            credential_device_type=str(verified.credential_device_type.value),
        )
    except Exception:
        dep("clear_passkey_session")(request.session)
        return dep("log_and_internal_server_error")(
            dep("logger"),
            f"Passkey authentication: failed to update credential usage for passkey {passkey['id']}",
            status="fail",
            message=ERROR_PASSKEY_USAGE_UPDATE_FAILED,
        )

    dep("establish_authenticated_session")(request, int(passkey["user_id"]), user["email"])
    dep("clear_passkey_session")(request.session)

    await _copy_default_tasks_after_login(
        int(passkey["user_id"]),
        context="Passkey authentication",
    )
    await _claim_guest_prompts_after_login(
        request,
        int(passkey["user_id"]),
        context="Passkey authentication",
    )

    return dep("jsonify")({"status": "success", "message": "Passkeyでログインしました"})
