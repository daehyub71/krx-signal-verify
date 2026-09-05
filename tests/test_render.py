"""render — 메일 본문 (F50·N9·N1·N3). **순수 함수.**

**간략하게.** 판정·점수·근거 발췌 + 대시보드 링크. 전문은 웹으로 보낸다.

지키는 것:
  · **판정·점수·공시·한계 문구는 어느 단계에서도 접지 않는다** (F50)
  · **102,400 bytes 이내** — 넘으면 Gmail이 잘라내고 **꼬리의 한계 문구까지 사라진다**.
    선행 첫 판이 149,971 bytes로 실제 절단됐다. 실제 `EmailMessage` 크기로 잰다 (N9)
  · **모든 공시에 DART 원문 링크** (N3)
  · **N1·N2 금지어가 본문 어디에도 없다** — 공시·뉴스 제목 원문은 예외
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from verify import render
from verify.models import Disclosure, Evidence, SignalRow, Verdict, VerdictPart

D = date(2026, 9, 3)


def sig(ticker: str = "005930", name: str = "삼성전자") -> SignalRow:
    return SignalRow(d=D, strategy="vcp", ticker=ticker, name=name,
                     evidence={"price": {"close": 70000, "change_pct": 2.5}})


def verdict(stand: str = "불일치", score: int = 20) -> Verdict:
    return Verdict(stand, score, (VerdictPart("🔴 1건", -8), VerdictPart("잠재 물량 18.6%", -19)),
                   ("재무", "공매도", "업황"), "1.0")


def evidence(ticker: str = "005930", n: int = 1) -> Evidence:
    return Evidence(
        d=D, ticker=ticker,
        disclosures=tuple(
            Disclosure(D, "전환사채권발행결정", f"2026090300{i:04d}") for i in range(n)
        ),
    )


def page(n: int = 1, **over: Any) -> dict[str, Any]:
    items = [
        (sig(f"{i:06d}", f"종목{i}"), verdict(), evidence(f"{i:06d}"), "설명 한 줄")
        for i in range(n)
    ]
    base: dict[str, Any] = {"d": D, "items": items, "url": "https://example.test"}
    base.update(over)
    return base


# ── 접지 않는 것 (F50) ────────────────────────────────────────────


def test_the_verdict_and_score_are_never_folded() -> None:
    """3단계 접기를 쓰더라도 **이 넷은 어느 단계에서도 접지 않는다.**"""
    html = render.html(**page(3))
    for part in ("불일치", "20"):
        assert part in html
    # 접기 안쪽(`<details>`)에 갇히지 않았는지 본다
    outside = html.split("<details")[0]
    assert "불일치" in outside


def test_the_limit_note_is_never_folded() -> None:
    """**꼬리가 잘리면 이 줄이 먼저 사라진다** — 그래서 앞쪽에 둔다."""
    html = render.html(**page(3))
    assert "앞으로의 주가를 말하지 않는다" in html.split("<details")[0]


def test_every_disclosure_has_its_dart_link() -> None:
    """N3 — 원문 없이 제목만 보내면 확인할 길이 없다."""
    html = render.html(**page(2))
    assert html.count("dart.fss.or.kr") >= 2


def test_the_dashboard_link_is_there() -> None:
    """전문은 웹으로 보낸다 (F50) — 링크가 없으면 메일이 전부여야 한다."""
    assert "https://example.test" in render.html(**page(1))


def test_no_signals_still_produces_a_mail() -> None:
    """신호 없는 날도 보낸다 — 안 오면 배치가 죽은 것인지 알 수 없다."""
    html = render.html(**page(0))
    assert html
    assert "없" in html


# ── N9 크기 예산 ──────────────────────────────────────────────────


def test_a_full_day_fits_the_budget() -> None:
    """**실제 `EmailMessage` 크기로 잰다** — HTML 문자열 길이가 아니다 (N9).

    선행 첫 판이 149,971 bytes로 Gmail에 잘렸고, **꼬리의 한계 문구까지 사라졌다.**
    """
    from verify import notify

    p = page(44)
    msg = notify.build_message(render.subject(D, 44), render.text(**p), render.html(**p),
                               "a@b.c", ["d@e.f"])
    assert len(bytes(msg)) < render.MAX_BYTES


def test_the_budget_is_the_gmail_one() -> None:
    assert render.MAX_BYTES == 102_400


def test_an_absurd_day_is_trimmed_not_truncated() -> None:
    """예산을 넘으면 **우리가 줄인다** — Gmail이 자르면 꼬리부터 사라진다."""
    from verify import notify

    p = page(400)
    html = render.html(**p)
    msg = notify.build_message(render.subject(D, 400), render.text(**p), html, "a@b.c", ["d@e.f"])
    assert len(bytes(msg)) < render.MAX_BYTES
    assert "앞으로의 주가를 말하지 않는다" in html  # 줄여도 한계 문구는 남는다


def test_trimming_says_that_it_trimmed() -> None:
    """조용히 줄이면 「그날은 40종목뿐이었나」로 읽힌다.

    **몇 종목을 뺐는지까지 적는다** — 「생략」이라는 말만으로는 「서술 생략」과 구별되지 않는다
    (변이 검사로 드러남: 느슨한 검사가 그 줄을 지워도 통과했다, 2026-09-05).
    """
    html = render.html(**page(400))
    cut = 400 - render.MAX_ITEMS
    assert str(cut) in html
    assert "메일에서 생략" in html


# ── 문구 (N1·N2) ─────────────────────────────────────────────────


def test_no_forbidden_words_in_our_own_text() -> None:
    from verify import wording

    p = page(3)
    for body in (render.html(**p), render.text(**p)):
        stripped = render.strip_quoted(body)
        assert not wording.has_forbidden(stripped), stripped[:200]
        assert not wording.has_forbidden_outcome(stripped), stripped[:200]


def test_a_quoted_headline_is_allowed_through() -> None:
    """공시·뉴스 **제목 원문은 예외다** — 우리 문장이 아니다."""
    items = [(sig(), verdict(), Evidence(d=D, ticker="005930", disclosures=(
        Disclosure(D, "주식등의대량보유상황보고서(매도)", "20260903000001"),
    )), "설명")]
    html = render.html(d=D, items=items, url="https://x")
    assert "매도" in html  # 제목은 그대로 실린다
    assert not wording.has_forbidden(render.strip_quoted(html))


from verify import wording  # noqa: E402

# ── 제목 ──────────────────────────────────────────────────────────


def test_the_subject_is_marked_as_verification() -> None:
    """병행 기간에 선행 `[브리핑]`과 섞이면 안 된다 (R11)."""
    assert render.subject(D, 15).startswith("[검증]")


def test_the_subject_carries_the_day_and_count() -> None:
    s = render.subject(D, 15)
    assert "09-03" in s or "2026-09-03" in s
    assert "15" in s


def test_a_quiet_day_says_so_in_the_subject() -> None:
    assert "검증 없음" in render.subject(D, 0)


# ── 서술이 없을 때 ────────────────────────────────────────────────


def test_a_missing_summary_is_marked_not_hidden() -> None:
    """**LLM이 죽어도 판정·점수·증거는 나간다** (F34) — 빈 자리를 표시한다."""
    items = [(sig(), verdict(), evidence(), "")]
    html = render.html(d=D, items=items, url="https://x")
    assert "불일치" in html
    assert "서술 생략" in html


# ── 노드 ──────────────────────────────────────────────────────────


def a_state(n: int = 2, **over: Any) -> Any:
    items = [
        (sig(f"{i:06d}", f"종목{i}"), verdict(), evidence(f"{i:06d}"), "설명") for i in range(n)
    ]
    base: dict[str, Any] = {
        "run_date": D,
        "signals": [s for s, _, _, _ in items],
        "evidence": [e for _, _, e, _ in items],
        "verdicts": {s.ticker: v for s, v, _, _ in items},
        "summaries": {s.ticker: t for s, _, _, t in items},
    }
    base.update(over)
    return base


def test_the_render_node_fills_subject_and_bodies() -> None:
    from verify import nodes

    out = nodes.render(a_state(2))
    assert out["subject"].startswith("[검증]")
    assert "불일치" in out["html"]
    assert out["text"]


def test_render_works_without_summaries() -> None:
    """LLM이 죽은 날 — 판정·점수는 그대로 나간다 (F34)."""
    from verify import nodes

    out = nodes.render(a_state(2, summaries={}))
    assert "불일치" in out["html"]
    assert "서술 생략" in out["html"]


def test_send_records_the_result_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """**예외를 밖으로 내지 않는다** — raise하면 `record_run`에 못 간다 (N11)."""
    from verify import nodes

    def boom(subject: str, text_: str, html_: str) -> int:
        raise RuntimeError("SMTP 인증 실패")

    monkeypatch.setattr(nodes, "_send", boom)
    out = nodes.send_email(cast(Any, {**a_state(1), "subject": "s", "text": "t", "html": "h"}))
    assert out["send"].ok is False
    assert "SMTP 인증 실패" in out["send"].reason


def test_dry_run_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--dry-run`은 **실패가 아니다** — 보내지 않았을 뿐이다."""
    from verify import nodes

    sent: list[Any] = []

    def spy(*a: Any) -> int:
        sent.append(a)
        return 1

    monkeypatch.setattr(nodes, "_send", spy)
    out = nodes.send_email(
        cast(Any, {**a_state(1), "dry_run": True, "subject": "s", "text": "t", "html": "h"})
    )
    assert sent == []
    assert out.get("send") is None or out["send"].ok


def test_the_mail_is_measured_before_it_goes(monkeypatch: pytest.MonkeyPatch) -> None:
    """**예산을 넘긴 채로 보내지 않는다** (N9) — Gmail이 자르면 꼬리가 사라진다."""
    from verify import nodes

    out = nodes.render(a_state(44))
    from verify import notify

    msg = notify.build_message(out["subject"], out["text"], out["html"], "a@b.c", ["d@e.f"])
    assert len(bytes(msg)) < render.MAX_BYTES


def test_both_nodes_are_no_longer_stubs() -> None:
    from verify import nodes

    assert nodes.STUB_NODES == ()


def test_the_html_body_is_actually_attached() -> None:
    """**본문이 안 담기면 빈 메일이 간다** — 크기 검사만으로는 안 걸린다."""
    from verify import notify

    msg = notify.build_message("s", "평문 본문", "<p>HTML 본문</p>", "a@b.c", ["d@e.f"])
    raw = bytes(msg).decode("utf-8", "replace")
    assert "HTML" in raw or "SFRNTA" in raw  # 인코딩돼도 어딘가 있어야 한다
    assert msg.get_body(("html",)) is not None
    assert msg.get_body(("plain",)) is not None


def test_the_worst_score_comes_first() -> None:
    """**눈에 먼저 띄어야 하는 것이 먼저다** — 불일치가 아래로 밀리면 못 본다."""
    from verify import nodes

    items = [
        (sig("000001", "높은점수"), verdict("정합", 68), evidence("000001"), "설명"),
        (sig("000002", "낮은점수"), verdict("불일치", 20), evidence("000002"), "설명"),
    ]
    s = {
        "run_date": D,
        "signals": [x[0] for x in items],
        "evidence": [x[2] for x in items],
        "verdicts": {x[0].ticker: x[1] for x in items},
        "summaries": {},
    }
    got = nodes._mail_items(cast(Any, s))
    assert [r[0].ticker for r in got] == ["000002", "000001"]


def test_the_credential_names_match_the_env_file() -> None:
    """⚠ **`GMAIL_USER`로 잘못 적었다** (2026-09-05). `.env`는 `GMAIL_ADDRESS`다.

    실행했다면 「환경변수 없음」으로 조용히 실패했을 것이고, 그건 발송 실패로만 보인다.
    `.env.example`이 정본이고, 코드가 그 이름을 쓰는지 여기서 대조한다.
    """
    import pathlib
    import re

    src = pathlib.Path("verify/notify.py").read_text(encoding="utf-8")
    example = pathlib.Path(".env.example").read_text(encoding="utf-8")
    declared = {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", example, re.M)}
    used = set(re.findall(r'config\.(?:require|optional)\("([A-Z0-9_]+)"', src))
    assert used <= declared, f".env.example에 없는 이름을 쓴다: {used - declared}"


def test_ondemand_never_sends_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    """**온디맨드는 게이트도 메일도 필요 없다** (V8) — 결과는 웹이 보여 준다.

    처음엔 `dry_run`만 봤다. ④ 경로를 쏘기 직전에 알았다 — 종목 하나짜리 「검증 없음」 메일이
    갈 뻔했다 (2026-09-05).
    """
    from verify import nodes
    from verify import state as st

    sent: list[Any] = []

    def spy(*a: Any) -> int:
        sent.append(a)
        return 1

    monkeypatch.setattr(nodes, "_send", spy)
    out = nodes.send_email(cast(Any, {
        **a_state(1), "mode": st.MODE_ONDEMAND, "ticker": "005930",
        "subject": "s", "text": "t", "html": "h",
    }))
    assert sent == []
    assert out.get("send") is None  # 실패도 아니다 — 안 보낸 것뿐이다


def test_batch_still_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    """반대편도 잠근다 — 배치는 보낸다."""
    from verify import nodes
    from verify import state as st

    sent: list[Any] = []

    def spy(*a: Any) -> int:
        sent.append(a)
        return 2

    monkeypatch.setattr(nodes, "_send", spy)
    out = nodes.send_email(cast(Any, {
        **a_state(1), "mode": st.MODE_BATCH, "subject": "s", "text": "t", "html": "h",
    }))
    assert len(sent) == 1
    assert out["send"].ok is True
