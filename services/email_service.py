import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

SEND_ADDRESS_ENV = "SEND_ADDRESS"
SEND_PASSWORD_ENV = "SEND_PASSWORD"
LEGACY_SEND_PASSWORD_ENV = "EMAIL_SEND_PASSWORD"


def _load_email_credentials() -> tuple[str, str]:
    # 新旧の環境変数を読み、未設定なら起動時ではなく送信時に明示的に失敗させる
    # Read current/legacy env vars and fail explicitly at send time if missing.
    send_address = (os.getenv(SEND_ADDRESS_ENV) or "").strip()
    send_password = (
        os.getenv(SEND_PASSWORD_ENV)
        or os.getenv(LEGACY_SEND_PASSWORD_ENV)
        or ""
    ).strip()
    if not send_address or not send_password:
        raise RuntimeError(
            "Email credentials are not configured. "
            f"Set {SEND_ADDRESS_ENV} and {SEND_PASSWORD_ENV}."
        )
    return send_address, send_password


def send_email(to_address: str, subject: str, body_text: str) -> None:
    # Gmail SMTP を使ってテキストメールを送信する
    # Send a plain-text email through Gmail SMTP.
    """指定アドレスにメール送信"""
    send_address, send_password = _load_email_credentials()
    with smtplib.SMTP("smtp.gmail.com", 587) as smtpobj:
        smtpobj.starttls()
        smtpobj.login(send_address, send_password)
        msg = MIMEText(body_text)
        msg['Subject'] = subject
        msg['From'] = send_address
        msg['To'] = to_address
        msg['Date'] = formatdate()
        smtpobj.send_message(msg)
