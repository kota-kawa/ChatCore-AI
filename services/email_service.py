import os

import requests

RESEND_API_URL = "https://api.resend.com/emails"
RESEND_API_KEY_ENV = "RESEND_API_KEY"
RESEND_FROM_ADDRESS_ENV = "RESEND_FROM_ADDRESS"
REQUEST_TIMEOUT_SECONDS = 10


def _load_resend_config() -> tuple[str, str]:
    # 起動時ではなく送信時に明示的に失敗させる。
    # Fail explicitly at send time instead of import/startup time.
    api_key = (os.getenv(RESEND_API_KEY_ENV) or "").strip()
    from_address = (os.getenv(RESEND_FROM_ADDRESS_ENV) or "").strip()
    if not api_key or not from_address:
        raise RuntimeError(
            "Resend email credentials are not configured. "
            f"Set {RESEND_API_KEY_ENV} and {RESEND_FROM_ADDRESS_ENV}."
        )
    return api_key, from_address


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


def send_email(to_address: str, subject: str, body_text: str) -> None:
    # Resend Email API を使ってテキストメールを送信する。
    # Send a plain-text email through the Resend Email API.
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
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code < 200 or response.status_code >= 300:
        detail = _extract_resend_error(response)
        raise RuntimeError(
            f"Resend email request failed with status {response.status_code}: {detail}"
        )
