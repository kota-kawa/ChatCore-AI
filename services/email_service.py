"""認証コードなどのメールを組み立て、Resend の API で送信する。
登録・ログイン・メールアドレス変更の各テンプレートを日本語・英語で持ち、プレーンテキストと HTML の両方を作る。

Builds and sends mails such as verification codes through the Resend API.
Holds Japanese and English templates for registration, sign-in and email-address change, and renders both text and HTML.
"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

import requests

from services import http_client
from services.i18n import get_request_locale

# 日本語: Resend の API 設定。認証情報は環境変数（RESEND_API_KEY / RESEND_FROM_ADDRESS）から読む。メール言語は ja / en のみ。
# English: Resend API settings. Credentials are read from the RESEND_API_KEY / RESEND_FROM_ADDRESS environment variables; mail locales are ja / en only.
RESEND_API_URL = "https://api.resend.com/emails"
RESEND_API_KEY_ENV = "RESEND_API_KEY"
RESEND_FROM_ADDRESS_ENV = "RESEND_FROM_ADDRESS"
REQUEST_TIMEOUT_SECONDS = 10
SUPPORTED_EMAIL_LOCALES = frozenset({"ja", "en"})

# 旧来のプレーンテキスト呼び出しとの互換性を保つ。新しい認証メールはcodeを明示する。
# Backward-compatible extraction for callers that still provide an unstructured
# plain-text body. New verification mail callers pass ``code`` explicitly.
LEGACY_VERIFICATION_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


# 日本語: メール 1 種類・1 言語ぶんの文言一式（件名・見出し・本文・注意書き・フッターなど）。
# English: The wording for one mail kind in one language (subject, heading, intro, note, footer and so on).
@dataclass(frozen=True)
class EmailTemplate:
    subject: str
    heading: str
    eyebrow: str
    intro: str
    note: str
    code_label: str
    footer: str


# 日本語: テンプレート種別 → 言語 → 文言の対応表。登録認証・ログイン認証・変更前メールの確認・変更先メールの確認がある。
# English: Map of template kind -> locale -> wording: registration, sign-in, current-address confirmation and new-address confirmation.
EMAIL_TEMPLATES: dict[str, dict[str, EmailTemplate]] = {
    "registration_verification": {
        "ja": EmailTemplate(
            subject="Chat-Core AI: アカウント認証コード",
            heading="アカウント認証コード",
            eyebrow="Chat-Core AIへようこそ",
            intro="以下の認証コードを登録画面に入力してください。",
            note="このコードを入力してアカウント登録を完了してください。",
            code_label="認証コード",
            footer="このメールはChat-Core AIから自動送信されています。返信は受け付けていません。",
        ),
        "en": EmailTemplate(
            subject="Chat-Core AI: Account verification code",
            heading="Account verification code",
            eyebrow="Welcome to Chat-Core AI",
            intro="Enter the following verification code on the registration screen.",
            note="Use this code to finish creating your account.",
            code_label="Verification code",
            footer="This automated message was sent by Chat-Core AI. Please do not reply.",
        ),
    },
    "login_verification": {
        "ja": EmailTemplate(
            subject="Chat-Core AI: ログイン認証コード",
            heading="ログイン認証コード",
            eyebrow="安全なログイン",
            intro="以下の認証コードをログイン画面に入力してください。",
            note="このコードはログイン画面でのみ使用してください。",
            code_label="認証コード",
            footer="このメールはChat-Core AIから自動送信されています。返信は受け付けていません。",
        ),
        "en": EmailTemplate(
            subject="Chat-Core AI: Sign-in verification code",
            heading="Sign-in verification code",
            eyebrow="Secure sign-in",
            intro="Enter the following verification code on the sign-in screen.",
            note="Only use this code on the Chat-Core AI sign-in screen.",
            code_label="Verification code",
            footer="This automated message was sent by Chat-Core AI. Please do not reply.",
        ),
    },
    "email_change_current": {
        "ja": EmailTemplate(
            subject="Chat-Core AI: メールアドレス変更の確認",
            heading="現在のメールアドレスを確認",
            eyebrow="アカウントセキュリティ",
            intro="メールアドレス変更のリクエストを受け付けました。以下の確認コードを設定画面に入力してください。",
            note="確認後、変更先メールアドレスにも確認コードを送信します。心当たりがない場合は、このメールを無視してください。",
            code_label="確認コード",
            footer="このメールはChat-Core AIから自動送信されています。返信は受け付けていません。",
        ),
        "en": EmailTemplate(
            subject="Chat-Core AI: Confirm your email address change",
            heading="Confirm your current email address",
            eyebrow="Account security",
            intro="We received a request to change your email address. Enter the following code in Settings.",
            note="After this step, we will send another code to your new address. If you did not request this change, ignore this email.",
            code_label="Verification code",
            footer="This automated message was sent by Chat-Core AI. Please do not reply.",
        ),
    },
    "email_change_new": {
        "ja": EmailTemplate(
            subject="Chat-Core AI: 新しいメールアドレスの確認",
            heading="新しいメールアドレスを確認",
            eyebrow="アカウントセキュリティ",
            intro="以下の確認コードを設定画面に入力すると、メールアドレスの変更が完了します。",
            note="心当たりがない場合は、このメールを無視してください。",
            code_label="確認コード",
            footer="このメールはChat-Core AIから自動送信されています。返信は受け付けていません。",
        ),
        "en": EmailTemplate(
            subject="Chat-Core AI: Verify your new email address",
            heading="Verify your new email address",
            eyebrow="Account security",
            intro="Enter the following code in Settings to finish changing your email address.",
            note="If you did not request this change, ignore this email.",
            code_label="Verification code",
            footer="This automated message was sent by Chat-Core AI. Please do not reply.",
        ),
    },
}


# 日本語: ロケール文字列を言語部分だけに正規化する。対応外・未指定は ja にする。
# English: Normalize a locale string to its language part, defaulting to ja when unsupported or missing.
def normalize_email_locale(locale: str | None) -> str:
    normalized = str(locale or "ja").strip().lower().replace("_", "-").split("-", 1)[0]
    return normalized if normalized in SUPPORTED_EMAIL_LOCALES else "ja"


def resolve_request_email_locale(request: object) -> str:
    """リクエストからメールの言語を決める。アプリ共通のロケール判定（get_request_locale）をそのまま使う。

    Resolve mail locale through the application's canonical request policy.
    """
    return normalize_email_locale(get_request_locale(request))  # type: ignore[arg-type]


# 日本語: Resend の API キーと送信元アドレスを環境変数から読む。どちらかが未設定なら送信せずに例外にする。
# English: Read the Resend API key and sender address from the environment; raise instead of sending if either is missing.
def _load_resend_config() -> tuple[str, str]:
    api_key = (os.getenv(RESEND_API_KEY_ENV) or "").strip()
    from_address = (os.getenv(RESEND_FROM_ADDRESS_ENV) or "").strip()
    if not api_key or not from_address:
        raise RuntimeError(
            "Resend email credentials are not configured. "
            f"Set {RESEND_API_KEY_ENV} and {RESEND_FROM_ADDRESS_ENV}."
        )
    return api_key, from_address


# 日本語: Resend のエラー応答から人が読めるメッセージを取り出す。JSON の形が複数あり得るため順に試し、なければ本文の先頭 300 文字を使う。
# English: Pull a readable message out of a Resend error response. Several JSON shapes are tried in turn, falling back to the first 300 characters of the body.
def _extract_resend_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
        error = payload.get("error")
        if isinstance(error, str) and error:
            return error
        if isinstance(error, dict):
            nested_message = error.get("message")
            if isinstance(nested_message, str) and nested_message:
                return nested_message
    return response.text[:300]


def render_verification_email(
    template_kind: str,
    *,
    code: str,
    locale: str | None = None,
    context: Mapping[str, object] | None = None,
) -> tuple[str, str]:
    """認証メールの件名と本文（プレーンテキスト）を作る。表示用の文面から種別などを推測せず、template_kind で明示的に選ぶ。
    メールアドレス変更では context の new_email を本文に添える。

    Render a verification email without parsing display text for metadata.
    For address changes, context["new_email"] is appended to the body.
    """
    localized_templates = EMAIL_TEMPLATES.get(template_kind)
    if localized_templates is None:
        raise ValueError(f"Unsupported email template kind: {template_kind}")
    resolved_locale = normalize_email_locale(locale)
    template = localized_templates[resolved_locale]
    lines = [template.intro, "", f"{template.code_label}: {code}"]
    new_email = str((context or {}).get("new_email") or "").strip()
    if new_email:
        label = "変更先メールアドレス" if resolved_locale == "ja" else "New email address"
        lines.extend(("", f"{label}: {new_email}"))
    lines.extend(("", template.note))
    return template.subject, "\n".join(lines)


# 日本語: 種別を渡さない旧呼び出し向けの互換処理。件名の文言からテンプレート種別を推測する。新しい呼び出しでは使わない。
# English: Compatibility for old callers that pass no kind: guess the template kind from the subject text. New callers do not use it.
def _legacy_template_kind(subject: str) -> str:
    # 非構造化呼び出し専用の互換処理。新しい呼び出しはkindを明示する。
    # Deprecated compatibility only. Structured callers always provide a kind.
    if "ログイン" in subject or "sign-in" in subject.lower() or "login" in subject.lower():
        return "login_verification"
    if "メールアドレス変更" in subject or "email address" in subject.lower():
        return "email_change_current"
    return "registration_verification"


# 日本語: プレーンテキスト本文から HTML メールを作る。メールクライアントで崩れにくいよう、table とインライン style で組む。
# 認証コードは引数で受け取り、旧呼び出しでは本文中の 6 桁の数字から取り出す。値はすべて html.escape で無害化する。
# English: Build the HTML mail from the plain-text body, using tables and inline styles so it survives mail clients.
# The code comes from the argument, or from a 6-digit number in the body for legacy callers. Every value is passed through html.escape.
def _build_email_html(
    subject: str,
    body_text: str,
    *,
    locale: str | None = None,
    template_kind: str | None = None,
    code: str | None = None,
) -> str:
    resolved_locale = normalize_email_locale(locale)
    kind = template_kind or _legacy_template_kind(subject)
    template = EMAIL_TEMPLATES.get(kind, EMAIL_TEMPLATES["registration_verification"])[resolved_locale]
    resolved_code = str(code or "").strip()
    if not resolved_code:
        match = LEGACY_VERIFICATION_CODE_PATTERN.search(body_text)
        resolved_code = match.group(1) if match else ""

    intro_lines = []
    for line in body_text.splitlines():
        stripped = line.strip()
        if not stripped or (resolved_code and resolved_code in stripped):
            continue
        intro_lines.append(stripped)
    intro_html = "".join(
        '<p style="margin:0 0 14px;color:#334155;font-size:15px;line-height:1.7;">'
        f"{html.escape(line)}</p>"
        for line in intro_lines
    ) or (
        '<p style="margin:0 0 14px;color:#334155;font-size:15px;line-height:1.7;">'
        f"{html.escape(template.intro)}</p>"
    )

    code_html = ""
    if resolved_code:
        code_html = f"""
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:22px 0 24px;">
            <tr><td align="center" style="background:#f8fafc;border:1px solid #dbeafe;border-radius:14px;padding:22px 16px;">
              <div aria-label="Verification code" style="color:#64748b;font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px;">{html.escape(template.code_label)}</div>
              <div style="font-family:'SFMono-Regular',Consolas,monospace;color:#0f172a;font-size:34px;font-weight:800;letter-spacing:.24em;line-height:1;">{html.escape(resolved_code)}</div>
            </td></tr>
          </table>"""

    return f"""<!doctype html>
<html lang="{resolved_locale}">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(subject)}</title></head>
  <body style="margin:0;padding:0;background:#eef2f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;color:transparent;opacity:0;">{html.escape(template.heading)} from Chat-Core AI</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef2f7;padding:32px 12px;"><tr><td align="center">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#fff;border-radius:18px;overflow:hidden;border:1px solid #dbe3ef;box-shadow:0 16px 42px rgba(15,23,42,.12);">
        <tr><td style="background:#0f172a;padding:26px 30px;"><div style="color:#fff;font-size:20px;font-weight:800;">Chat-Core AI</div><div style="color:#93c5fd;font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin-top:8px;">{html.escape(template.eyebrow)}</div></td></tr>
        <tr><td style="padding:30px;"><h1 style="margin:0 0 16px;color:#0f172a;font-size:24px;line-height:1.3;font-weight:800;">{html.escape(template.heading)}</h1>{intro_html}{code_html}<div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:14px 16px;color:#9a3412;font-size:13px;line-height:1.6;">{html.escape(template.note)}</div></td></tr>
        <tr><td style="padding:20px 30px;background:#f8fafc;border-top:1px solid #e2e8f0;color:#64748b;font-size:12px;line-height:1.6;">{html.escape(template.footer)}</td></tr>
      </table>
    </td></tr></table>
  </body>
</html>"""


def send_email(
    to_address: str,
    subject: str | None = None,
    body_text: str | None = None,
    *,
    template_kind: str | None = None,
    code: str | None = None,
    locale: str | None = None,
    context: Mapping[str, object] | None = None,
) -> None:
    """メールを Resend 経由で送信する。template_kind と code を渡すと、言語別の認証メールのテンプレートで件名と本文を作る。
    それ以外は subject と body_text が必須。送信に失敗（2xx 以外）したら RuntimeError にする。

    Send email, optionally rendering a typed localized verification template.
    Without template_kind, subject and body_text are required. A non-2xx response raises RuntimeError.
    """
    if template_kind:
        if not code:
            raise ValueError("code is required when template_kind is provided")
        subject, body_text = render_verification_email(
            template_kind,
            code=str(code),
            locale=locale,
            context=context,
        )
    if subject is None or body_text is None:
        raise ValueError("subject and body_text are required")

    api_key, from_address = _load_resend_config()
    response = http_client.post(
        RESEND_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Chat-Core/1.0",
        },
        json={
            "from": from_address,
            "to": [to_address],
            "subject": subject,
            "text": body_text,
            "html": _build_email_html(
                subject,
                body_text,
                locale=locale,
                template_kind=template_kind,
                code=code,
            ),
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code < 200 or response.status_code >= 300:
        detail = _extract_resend_error(response)
        raise RuntimeError(f"Resend email request failed with status {response.status_code}: {detail}")
