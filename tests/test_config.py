"""환경변수 로더 — 이미 설정된 값을 덮어쓰지 않는 것이 핵심이다."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from verify import config


def test_load_env_reads_key_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KSV_T_A", raising=False)
    p = tmp_path / ".env"
    p.write_text("KSV_T_A=hello\n", encoding="utf-8")
    config.load_env(p)
    assert os.environ["KSV_T_A"] == "hello"


def test_load_env_does_not_overwrite_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI Secrets가 먼저 주입된다. 로컬 .env가 그것을 덮으면 원인을 못 찾는 사고가 난다."""
    monkeypatch.setenv("KSV_T_B", "from-ci")
    p = tmp_path / ".env"
    p.write_text("KSV_T_B=from-dotenv\n", encoding="utf-8")
    config.load_env(p)
    assert os.environ["KSV_T_B"] == "from-ci"


def test_load_env_skips_comments_blanks_and_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for k in ("KSV_T_C", "KSV_T_D"):
        monkeypatch.delenv(k, raising=False)
    p = tmp_path / ".env"
    p.write_text("# 주석\n\n키없는줄\nKSV_T_C=ok\n  KSV_T_D = spaced  \n", encoding="utf-8")
    config.load_env(p)
    assert os.environ["KSV_T_C"] == "ok"
    assert os.environ["KSV_T_D"] == "spaced"


def test_load_env_strips_quotes_but_keeps_inner_equals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB URL에 '='가 들어간다. 첫 '='에서만 잘라야 한다."""
    for k in ("KSV_T_E", "KSV_T_F"):
        monkeypatch.delenv(k, raising=False)
    dsn = "postgresql://USER:NOT_A_REAL_PASSWORD@HOST/db?sslmode=require"
    p = tmp_path / ".env"
    p.write_text(f'KSV_T_E="quoted"\nKSV_T_F={dsn}\n', encoding="utf-8")
    config.load_env(p)
    assert os.environ["KSV_T_E"] == "quoted"
    assert os.environ["KSV_T_F"] == dsn


def test_load_env_missing_file_is_silent(tmp_path: Path) -> None:
    """CI에는 .env가 없다. 조용히 넘어가야 한다."""
    config.load_env(tmp_path / "nope.env")


def test_require_raises_when_missing_or_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KSV_T_G", raising=False)
    with pytest.raises(RuntimeError, match="KSV_T_G"):
        config.require("KSV_T_G")
    monkeypatch.setenv("KSV_T_G", "   ")
    with pytest.raises(RuntimeError):
        config.require("KSV_T_G")


def test_require_message_names_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """어떤 키가 비었는지 말해 줘야 한다 — 이름 없이 실패하면 원인을 못 찾는다."""
    monkeypatch.delenv("KSV_T_H", raising=False)
    with pytest.raises(RuntimeError) as e:
        config.require("KSV_T_H")
    assert "KSV_T_H" in str(e.value)


def test_optional_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KSV_T_I", raising=False)
    assert config.optional("KSV_T_I") == ""
    assert config.optional("KSV_T_I", "fallback") == "fallback"


def test_mask_hides_secret_in_url() -> None:
    """DART 키는 URL 쿼리에 실린다. 예외·로그에 URL을 통째로 찍지 않는다 (N10)."""
    url = "https://opendart.fss.or.kr/api/list.json?crtfc_key=abcd1234&corp_code=00126380"
    assert config.mask(url, "abcd1234") == (
        "https://opendart.fss.or.kr/api/list.json?crtfc_key=***&corp_code=00126380"
    )
    assert config.mask("no key here", "") == "no key here"
