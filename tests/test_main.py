"""CLI — 초기 상태를 만들어 그래프에 넘기고 종료 코드를 정한다.

**전략도 노드도 「오늘」을 스스로 알지 않는다** — 기준일은 여기서 주입한다.
그래야 드라이런과 재현이 성립한다.
"""

from __future__ import annotations

from datetime import UTC, date
from typing import Any

import pytest

from tests.conftest import collects, gate_returns, one_evidence, sent_fail, sent_ok
from verify import main as m
from verify import state as st

# ── 기준일 ───────────────────────────────────────────────────────


def test_date_flag_is_parsed() -> None:
    assert m.parse_args(["--date", "20260901"]).run_date == date(2026, 9, 1)


def test_default_date_is_seoul_not_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """UTC 15:30은 KST로 **다음 날 00:30**이다. UTC로 잡으면 그 시간대에 하루 밀린다.

    실제 시각에 기대면 한국 낮에는 두 값이 같아 **버그를 못 잡는다** — 경계를 고정해 본다.
    """
    from datetime import datetime as real_datetime

    frozen = real_datetime(2026, 9, 1, 15, 30, tzinfo=UTC)

    class FrozenDatetime:
        @staticmethod
        def now(tz: Any = None) -> Any:
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

        @staticmethod
        def utcnow() -> Any:
            return frozen.replace(tzinfo=None)

        @staticmethod
        def strptime(raw: str, fmt: str) -> Any:
            return real_datetime.strptime(raw, fmt)

    monkeypatch.setattr(m, "datetime", FrozenDatetime)
    assert m.parse_args([]).run_date == date(2026, 9, 2)


def test_bad_date_is_rejected_loudly() -> None:
    with pytest.raises(SystemExit):
        m.parse_args(["--date", "2026-09-01"])


# ── 모드 ─────────────────────────────────────────────────────────


def test_ticker_switches_to_ondemand() -> None:
    s = m.initial_state(m.parse_args(["--ticker", "042700"]))
    assert s["mode"] == st.MODE_ONDEMAND
    assert s["ticker"] == "042700"


def test_no_ticker_is_batch() -> None:
    assert m.initial_state(m.parse_args([]))["mode"] == st.MODE_BATCH


def test_ticker_may_contain_letters() -> None:
    """`0126Z0`이 실재한다. 숫자로 가정하면 종목이 조용히 누락된다."""
    assert m.parse_args(["--ticker", "0126Z0"]).ticker == "0126Z0"


@pytest.mark.parametrize("bad", ["42700", "0427000", "04270a", "04-700"])
def test_malformed_ticker_is_rejected(bad: str) -> None:
    with pytest.raises(SystemExit):
        m.parse_args(["--ticker", bad])


# ── 플래그 ───────────────────────────────────────────────────────


def test_flags_land_in_the_state() -> None:
    s = m.initial_state(m.parse_args(["--dry-run", "--force"]))
    assert s["dry_run"] is True and s["force"] is True


def test_flags_default_to_false() -> None:
    s = m.initial_state(m.parse_args([]))
    assert s["dry_run"] is False and s["force"] is False


def test_initial_state_seeds_nothing_else() -> None:
    """노드가 채울 키를 미리 넣지 않는다 — 스텁이 통과했는지 구분이 안 된다."""
    assert set(m.initial_state(m.parse_args([]))) == {
        "mode", "run_date", "ticker", "force", "dry_run"
    }


# ── 걷는 해골 — 스텁으로 START→END 완주 ─────────────────────────


def wired(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"gate": gate_returns(st.GATE_READY), "fetch_signals": collects(2),
                            "fetch_one": one_evidence, "send_email": sent_ok}
    base.update(over)
    return base


def test_walking_skeleton_completes_with_stubs() -> None:
    """M0의 완료 조건 — 스텁만으로 START에서 END까지 간다."""
    code = m.main([], overrides=wired())
    assert code == 0


def test_dry_run_finishes_zero_without_sending() -> None:
    sent: list[int] = []
    over = wired(send_email=lambda _: sent.append(1) or {})  # type: ignore[func-returns-value]
    assert m.main(["--dry-run"], overrides=over) == 0


# ── 종료 코드 — 부분 성공을 성공으로 위장하지 않는다 ─────────────


@pytest.mark.parametrize(
    "over,expected",
    [
        (wired(), 0),
        (wired(fetch_signals=collects(0)), 0),
        (wired(send_email=sent_fail), 1),
        (wired(gate=gate_returns(st.GATE_MISSING)), 1),
        (wired(gate=gate_returns(st.GATE_STALE)), 1),
    ],
)
def test_exit_code_follows_status(over: dict[str, Any], expected: int) -> None:
    assert m.main([], overrides=over) == expected


def test_io_failure_still_exits_not_crashes() -> None:
    """I/O가 터져도 프로세스는 기록을 남기고 정상 종료한다 — 스택 트레이스로 죽지 않는다."""
    def boom(_: Any) -> dict[str, Any]:
        raise RuntimeError("터짐")

    assert m.main([], overrides=wired(explain=boom)) == 0


# ── --if-not-verified ────────────────────────────────────────────


def test_if_not_verified_is_a_noop_when_already_done() -> None:
    """예비 cron용. 이미 돌았으면 두 번 보내지 않는다."""
    ran: list[int] = []
    code = m.main(
        ["--if-not-verified"],
        overrides=wired(gate=lambda _: ran.append(1) or {}),  # type: ignore[func-returns-value]
        verified_check=lambda _: True,
    )
    assert code == 0 and ran == []


def test_if_not_verified_runs_when_not_done() -> None:
    assert m.main(["--if-not-verified"], overrides=wired(), verified_check=lambda _: False) == 0


def test_force_overrides_the_noop() -> None:
    """`--force`는 이미 돌았어도 **실제로 다시 돈다** — 종료 코드만 보면 구분이 안 된다."""
    ran: list[int] = []

    def tracking_gate(_: Any) -> dict[str, Any]:
        ran.append(1)
        return {"gate": st.GATE_READY}

    code = m.main(
        ["--if-not-verified", "--force"],
        overrides=wired(gate=tracking_gate),
        verified_check=lambda _: True,
    )
    assert code == 0
    assert ran == [1], "--force인데 no-op으로 빠져나갔다"
