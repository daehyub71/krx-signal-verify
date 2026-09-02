"""환경변수 로딩.

외부 패키지(python-dotenv)를 쓰지 않는다 — 최소 의존성 원칙.
CI에서는 깃허브 Secrets가 환경변수로 먼저 주입되므로 **이미 설정된 값을 덮어쓰지 않는다.**
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> None:
    """`.env`를 읽어 환경변수에 채운다.

    Args:
        path: `.env` 경로. None이면 프로젝트 루트의 `.env`.

    Note:
        **이미 설정된 환경변수는 건드리지 않는다.** 로컬 `.env`가 CI Secrets를 덮으면
        원인을 찾기 매우 어려운 사고가 난다. 파일이 없으면 조용히 넘어간다 — CI에는 없다.
    """
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # 첫 '='에서만 자른다 — DB URL에 '='가 들어간다 (`?sslmode=require`).
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("\"'")


def require(key: str) -> str:
    """필수 환경변수를 읽는다. 없으면 즉시 실패한다.

    Args:
        key: 환경변수 이름.

    Returns:
        값 (양끝 공백 제거).

    Raises:
        RuntimeError: 값이 없거나 비어 있을 때. **메시지에 값을 넣지 않는다** (N10) —
            로그로 새는 첫 경로다. 조용히 빈 문자열로 흘려보내지도 않는다.
    """
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"환경변수 {key}가 없다. .env 또는 깃허브 Secrets를 확인하라.")
    return value


def optional(key: str, default: str = "") -> str:
    """선택 환경변수를 읽는다. 없으면 기본값."""
    return os.environ.get(key, default).strip()


def mask(text: str, secret: str) -> str:
    """문자열에서 비밀값을 가린다.

    DART 인증키는 **URL 쿼리에 실린다** — 예외 메시지나 로그에 URL을 통째로 찍으면
    거기서 샌다 (N10). 빈 secret은 아무것도 바꾸지 않는다.
    """
    return text.replace(secret, "***") if secret else text
