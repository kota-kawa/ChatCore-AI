import html
import os
import re

import requests

RESEND_API_URL = "https://api.resend.com/emails"
RESEND_API_KEY_ENV = "RESEND_API_KEY"
RESEND_FROM_ADDRESS_ENV = "RESEND_FROM_ADDRESS"
REQUEST_TIMEOUT_SECONDS = 10
VERIFICATION_CODE_PATTERN = re.compile(r"(?:認証コード|確認コード):\s*(\d{6})")


# 日本語: 環境変数からResend APIキーと送信元アドレスを読み込みます。
# English: Load the Resend API key and sender address from environment variables.
def _load_resend_config() -> tuple[str, str]:
    # 起動時ではなく送信時に明示的に失敗させる。
    # Fail explicitly at send time instead of import/startup time.
    api_key = (os.getenv(RESEND_API_KEY_ENV) or "").strip()
    from_address = (os.getenv(RESEND_FROM_ADDRESS_ENV) or "").strip()
    # 日本語: APIキーまたは送信元アドレスが設定されていない場合はエラーを発生させます。
    # English: Raise an error if the API key or sender address is not configured.
    if not api_key or not from_address:
        raise RuntimeError(
            "Resend email credentials are not configured. "
            f"Set {RESEND_API_KEY_ENV} and {RESEND_FROM_ADDRESS_ENV}."
        )
    return api_key, from_address


# 日本語: Resend APIからのエラーレスポンスを解析し、エラーメッセージを抽出します。
# English: Parse the error response from Resend API and extract the error message.
def _extract_resend_error(response: requests.Response) -> str:
    # 日本語: レスポンスをJSONとして解析し、エラー詳細の抽出を試みます。
    # English: Try to parse the response as JSON to extract error details.
    try:
        payload = response.json()
    except ValueError:
        payload = None

    # 日本語: 解析されたJSONオブジェクトからエラーメッセージを取り出します。
    # English: Extract the error message from the parsed JSON object.
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


# 日本語: 件名と本文テキストに基づいて、整えられたHTMLメール本文を構築します。
# English: Build a well-formatted HTML email body based on the subject and plain text content.
def _build_email_html(subject: str, body_text: str) -> str:
    code_match = VERIFICATION_CODE_PATTERN.search(body_text)
    code = code_match.group(1) if code_match else ""
    intro_lines = [
        line.strip()
        for line in body_text.splitlines()
        if line.strip() and not VERIFICATION_CODE_PATTERN.search(line)
    ]
    intro_html = "".join(
        (
            '<p style="margin:0 0 14px;color:#334155;font-size:15px;'
            'line-height:1.7;">'
            f"{html.escape(line)}"
            "</p>"
        )
        for line in intro_lines
    )
    # 日本語: 本文HTMLが空の場合、デフォルトの案内文を設定します。
    # English: Set a default notification message if the body HTML is empty.
    if not intro_html:
        intro_html = (
            '<p style="margin:0 0 14px;color:#334155;font-size:15px;line-height:1.7;">'
            "Chat-Core AI からのお知らせです。"
            "</p>"
        )

    # 日本語: メールの件名に応じて、見出しや説明文を切り替えます。
    # English: Customize the heading and notes based on the email subject.
    if "ログイン" in subject:
        heading = "ログイン認証コード"
        eyebrow = "Secure sign-in"
        note = "このコードはログイン画面でのみ使用してください。"
    elif "メールアドレス変更" in subject:
        heading = "メールアドレス変更の確認"
        eyebrow = "Account security"
        note = "心当たりがない場合は、このメールを無視してください。"
    else:
        heading = "アカウント認証コード"
        eyebrow = "Welcome to Chat-Core AI"
        note = "このコードを入力してアカウント登録を完了してください。"

    code_html = ""
    if code:
        escaped_code = html.escape(code)
        code_html = f"""
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:22px 0 24px;">
                      <tr>
                        <td align="center" style="background:#f8fafc;border:1px solid #dbeafe;border-radius:14px;padding:22px 16px;">
                          <div style="color:#64748b;font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px;">Verification code</div>
                          <div style="font-family:'SFMono-Regular',Consolas,'Liberation Mono',monospace;color:#0f172a;font-size:34px;font-weight:800;letter-spacing:.24em;line-height:1;">{escaped_code}</div>
                        </td>
                      </tr>
                    </table>
        """

    escaped_subject = html.escape(subject)
    escaped_heading = html.escape(heading)
    escaped_eyebrow = html.escape(eyebrow)
    escaped_note = html.escape(note)
    return f"""<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{escaped_subject}</title>
  </head>
  <body style="margin:0;padding:0;background:#eef2f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;color:transparent;opacity:0;">{escaped_heading} from Chat-Core AI</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef2f7;padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #dbe3ef;box-shadow:0 16px 42px rgba(15,23,42,.12);">
            <tr>
              <td style="background:#0f172a;padding:26px 30px;">
                <div style="color:#ffffff;font-size:20px;font-weight:800;letter-spacing:.02em;">Chat-Core AI</div>
                <div style="color:#93c5fd;font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin-top:8px;">{escaped_eyebrow}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:30px;">
                <h1 style="margin:0 0 16px;color:#0f172a;font-size:24px;line-height:1.3;font-weight:800;">{escaped_heading}</h1>
                {intro_html}
                {code_html}
                <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:14px 16px;color:#9a3412;font-size:13px;line-height:1.6;">
                  {escaped_note}
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 30px;background:#f8fafc;border-top:1px solid #e2e8f0;color:#64748b;font-size:12px;line-height:1.6;">
                This message was sent by Chat-Core AI. Please do not reply to this automated email.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


# 日本語: 指定されたメールアドレスにメールを送信します。
# English: Send an email to the specified email address.
def send_email(to_address: str, subject: str, body_text: str) -> None:
    # Resend Email API を使って HTML とテキストの両方を送信する。
    # Send both HTML and plain-text email through the Resend Email API.
    """指定アドレスにメール送信"""
    api_key, from_address = _load_resend_config()
    response = requests.post(
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
            "html": _build_email_html(subject, body_text),
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    # 日本語: レスポンスステータスが成功（2xx）でない場合はエラーを発生させます。
    # English: Raise an error if the response status code is not successful (2xx).
    if response.status_code < 200 or response.status_code >= 300:
        detail = _extract_resend_error(response)
        raise RuntimeError(
            f"Resend email request failed with status {response.status_code}: {detail}"
        )
