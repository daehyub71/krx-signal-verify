"""Gmail SMTP 발송 (M5). 표준 라이브러리 + `certifi`만 쓴다 (N4).

macOS 파이썬은 CA 번들이 없어 `certifi`를 명시적으로 준다 — 이 맥에는 TLS 인터셉션도 있다.

**예외를 밖으로 낸다.** 삼키는 것은 노드의 몫이고(`send_email`이 `SendResult`에 적는다),
여기서 조용히 실패하면 「보냈는데 안 왔다」와 「안 보냈다」를 구별할 수 없다.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import certifi

from verify import config

HOST, PORT, TIMEOUT = "smtp.gmail.com", 587, 30


def recipients() -> list[str]:
    """`RECIPIENTS` 환경변수 (쉼표 구분)."""
    return [x.strip() for x in config.optional("RECIPIENTS").split(",") if x.strip()]


def build_message(
    subject: str, text: str, html: str, sender: str, to: list[str]
) -> EmailMessage:
    """메일 하나. **크기 검사는 이것으로 잰다** — HTML 문자열 길이가 아니다 (N9)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send(subject: str, text: str, html: str) -> int:
    """보낸다. 받는 사람 수를 돌려준다.

    Raises:
        RuntimeError: 자격증명·수신자가 없다.
        smtplib.SMTPException · OSError: 인증·연결 실패. **호출 노드가 잡아 상태에 적는다.**
    """
    sender, password = config.require("GMAIL_USER"), config.require("GMAIL_APP_PASSWORD")
    to = recipients()
    if not to:
        raise RuntimeError("RECIPIENTS가 비었다")
    msg = build_message(subject, text, html, sender, to)
    ctx = ssl.create_default_context(cafile=certifi.where())
    with smtplib.SMTP(HOST, PORT, timeout=TIMEOUT) as s:
        s.starttls(context=ctx)
        s.login(sender, password)
        s.send_message(msg)
    return len(to)
