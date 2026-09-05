"""financial — 주요계정 원본 → 사실 몇 줄 (F30·F31). **순수 함수. I/O 없음.**

계약 테스트는 실제 응답 표본(`tests/fixtures/dart_multiacnt.json`)으로 한다 —
일반 회사(000500)와 **금융사**(016360 삼성증권) 둘.

지키는 것:
  · **표시는 사실만** (F30) — 매출·영업이익·당기순이익 전기 대비, 부채비율, 이익잉여금 부호.
    밸류에이션(PER·PBR)은 v1에서 계산하지 않는다
  · **못 찾으면 비우고 그렇다고 적는다** (F31) — 금융사에는 `매출액`이 없다(실측).
    `순이자손익`을 그 자리에 넣는 것이 **억지 매핑**이고, SPEC이 금지한다 (R7)
  · **표기 변형은 억지 매핑이 아니다** — `영업이익`과 `영업이익(손실)`은 같은 계정의 두 표기다.
    일반 회사도 `당기순이익(손실)`로 온다
  · **자본잠식이면 부채비율을 내지 않는다** — 자본총계가 0 이하면 음수가 나와 오해를 부른다
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from verify import financial
from verify.dart_fin import Accounts

FIX = pathlib.Path(__file__).parent / "fixtures"
SAMPLE: dict[str, Any] = json.loads((FIX / "dart_multiacnt.json").read_text(encoding="utf-8"))

GEN, FIN = "00104768", "00104856"
HALF = ("2026", "11012")


def accounts(corp: str, **over: Any) -> Accounts:
    items = [dict(x) for x in SAMPLE["list"] if x["corp_code"] == corp]
    for it in items:
        it.update(over)
    return Accounts(corp_code=corp, report=HALF, items=tuple(items))


def only(corp: str, *names: str) -> Accounts:
    items = [dict(x) for x in SAMPLE["list"] if x["corp_code"] == corp and x["account_nm"] in names]
    return Accounts(corp_code=corp, report=HALF, items=tuple(items))


# ── 일반 회사 (F30) ───────────────────────────────────────────────


def test_ordinary_company_reads_all_five_facts() -> None:
    f = financial.read(accounts(GEN))
    assert f.revenue is not None and f.revenue.now == 869_390_198_000
    assert f.operating is not None and f.operating.now == 36_131_796_000
    assert f.net is not None and f.net.now == 22_859_159_000
    assert f.debt_ratio is not None
    assert f.retained == 409_499_473_000
    assert f.absent == ()


def test_change_is_against_the_same_period_last_year() -> None:
    """IS의 전기는 **전년 동기**다 (`제 78 기반기`) — 반기 대 반기라 비교가 성립한다."""
    f = financial.read(accounts(GEN))
    assert f.revenue is not None
    assert f.revenue.prev == 643_289_510_000
    assert f.revenue.pct == pytest.approx(35.1, abs=0.1)
    assert f.revenue.period == "제 78 기반기"


def test_debt_ratio_is_liabilities_over_equity() -> None:
    f = financial.read(accounts(GEN))
    assert f.debt_ratio == pytest.approx(1_130_963_256_000 / 530_248_211_000 * 100, abs=0.1)
    assert f.debt_ratio == pytest.approx(213.3, abs=0.1)


def test_retained_earnings_sign_is_reported() -> None:
    """음수면 결손금이다 — 부호가 사실이다."""
    assert financial.read(accounts(GEN)).retained_is_deficit is False
    neg = accounts(GEN)
    items = tuple(
        {**x, "thstrm_amount": "-1,000"} if x["account_nm"] == "이익잉여금" else x
        for x in neg.items
    )
    f = financial.read(Accounts(GEN, HALF, items))
    assert f.retained == -1000
    assert f.retained_is_deficit is True


def test_report_label_travels_with_the_facts() -> None:
    """종목마다 기준 시점이 다르다 — 근거에 함께 실려야 한다 (F30b)."""
    assert financial.read(accounts(GEN)).report == "2026년 반기보고서"


# ── F31 금융사 — 비우고 그렇다고 적는다 ───────────────────────────


def test_financial_firm_has_no_revenue_and_says_so() -> None:
    """**이 파일의 요점.** 삼성증권에 `매출액`이 없다(실측). 비우고 이름을 남긴다."""
    f = financial.read(accounts(FIN))
    assert f.revenue is None
    assert f.has_revenue is False
    assert "매출액" in f.absent


def test_a_financial_account_is_never_used_as_revenue() -> None:
    """`순이자손익`·`순수수료손익`을 매출액 자리에 넣는 것이 억지 매핑이다 (R7)."""
    f = financial.read(accounts(FIN))
    assert f.revenue is None
    labels = {name for name, _ in f.extra}
    assert "순이자손익" in labels  # 제 이름으로 따로 실린다
    assert "순수수료손익" in labels


def test_financial_firm_still_has_operating_profit() -> None:
    """`영업이익(손실)`은 **같은 계정의 다른 표기**다 — 이건 비우면 안 된다."""
    f = financial.read(accounts(FIN))
    assert f.operating is not None
    assert f.operating.now == 675_794_814_040
    assert "영업이익" not in f.absent


def test_label_variants_are_one_account() -> None:
    assert financial.normalize("영업이익(손실)") == "영업이익"
    assert financial.normalize("당기순이익(손실)") == "당기순이익"
    assert financial.normalize("영업이익") == "영업이익"
    assert financial.normalize(" 법인세차감전 순이익 ") == "법인세차감전순이익"


def test_extra_accounts_are_not_invented() -> None:
    """일반 회사에 없는 계정을 지어내지 않는다."""
    assert financial.read(accounts(GEN)).extra == ()
    assert financial.read(accounts(GEN)).has_revenue is True


def test_the_module_never_declares_an_industry() -> None:
    """**계정 이름으로 업종을 추측하지 않는다** (R7).

    「고유 계정이 있으면 금융사」로 봤다가 44종목 실측에서 **아세아제지(종이·목재)가
    금융사로 잡혔다** — `차입부채`는 제조업도 쓴다 (2026-09-05).
    남는 사실은 「매출액을 못 찾았다」 하나뿐이다.
    """
    import pathlib as _p

    src = _p.Path(financial.__file__).read_text(encoding="utf-8")
    assert "is_financial_firm" not in src
    fields = set(financial.Financial.__dataclass_fields__)
    assert not any("firm" in f or "industry" in f or "sector" in f for f in fields), fields


def test_extra_accounts_can_appear_without_missing_revenue() -> None:
    """차입부채를 쓰면서 매출액도 정상인 회사가 실재한다 (아세아제지)."""
    items = tuple(x for x in accounts(GEN).items) + (
        _row("차입부채", "5,000", "20"),
    )
    f = financial.read(Accounts(GEN, HALF, items))
    assert f.has_revenue is True
    assert ("차입부채", f.extra[0][1]) == f.extra[0]
    assert "매출액" not in f.absent


def test_missing_debt_columns_are_named_in_absent() -> None:
    f = financial.read(only(GEN, "매출액", "영업이익"))
    assert f.debt_ratio is None
    assert "부채비율" in f.absent
    assert "이익잉여금" in f.absent


def test_absent_never_invents_a_zero() -> None:
    """0으로 채우면 「매출 0원」·「부채비율 0%」라는 없는 사실이 생긴다."""
    f = financial.read(Accounts(GEN, HALF, ()))
    assert (f.revenue, f.operating, f.net, f.debt_ratio, f.retained) == (None,) * 5
    assert set(f.absent) >= {"매출액", "영업이익", "당기순이익", "부채비율", "이익잉여금"}


# ── 연결 vs 개별 ──────────────────────────────────────────────────


def test_consolidated_is_preferred() -> None:
    """`CFS`(연결)·`OFS`(개별)가 **같은 계정으로 두 번** 온다 — 하나를 골라야 한다."""
    f = financial.read(accounts(GEN))
    assert f.basis == "연결"
    assert f.revenue is not None and f.revenue.now == 869_390_198_000


def test_separate_is_used_when_there_is_no_consolidated() -> None:
    items = tuple(x for x in accounts(GEN).items if x["fs_div"] == "OFS")
    f = financial.read(Accounts(GEN, HALF, items))
    assert f.basis == "개별"
    assert f.revenue is not None


def test_the_two_bases_are_never_mixed() -> None:
    """연결 매출과 개별 부채를 한 표에 섞으면 부채비율이 실재하지 않는 값이 된다."""
    items = tuple(
        x for x in accounts(GEN).items
        if (x["fs_div"] == "CFS" and x["sj_div"] == "IS")
        or (x["fs_div"] == "OFS" and x["sj_div"] == "BS")
    )
    f = financial.read(Accounts(GEN, HALF, items))
    assert f.basis == "연결"
    assert f.revenue is not None  # 연결 손익은 있다
    assert f.debt_ratio is None  # 연결 재무상태표가 없으니 비운다
    assert "부채비율" in f.absent


# ── 숫자 읽기 ─────────────────────────────────────────────────────


def test_duplicate_accounts_take_the_first_by_ord() -> None:
    """`당기순이익(손실)`이 `ord`만 다르게 두 번 온다 (실측 — 표본은 값이 같다)."""
    f = financial.read(accounts(GEN))
    assert f.net is not None and f.net.now == 22_859_159_000


def _row(name: str, now: str, ord_: str) -> dict[str, Any]:
    return {
        "corp_code": GEN, "fs_div": "CFS", "sj_div": "IS", "account_nm": name,
        "thstrm_amount": now, "frmtrm_amount": "1", "frmtrm_nm": "제 78 기반기", "ord": ord_,
    }


def test_when_duplicates_differ_the_lower_ord_wins() -> None:
    """값이 갈리면 어느 쪽인지가 사실을 바꾼다 — 연결 합계가 먼저 오고, 지분 분해가 뒤에 온다.

    표본은 두 줄의 값이 같아 이 규칙이 **관측되지 않았다** (변이 검사로 드러남, 2026-09-05).
    """
    got = financial.read(Accounts(GEN, HALF, (
        _row("당기순이익(손실)", "900", "13"),
        _row("당기순이익(손실)", "100", "14"),  # 비지배지분 몫 같은 것
    )))
    assert got.net is not None and got.net.now == 900


def test_order_of_arrival_does_not_decide() -> None:
    """응답 순서가 뒤집혀도 `ord`가 정한다."""
    got = financial.read(Accounts(GEN, HALF, (
        _row("당기순이익(손실)", "100", "14"),
        _row("당기순이익(손실)", "900", "13"),
    )))
    assert got.net is not None and got.net.now == 900


@pytest.mark.parametrize(
    ("raw", "want"),
    [("1,234", 1234), ("-1,234", -1234), ("0", 0), ("", None), ("-", None), (None, None)],
)
def test_amounts_parse_with_commas_and_blanks(raw: Any, want: int | None) -> None:
    assert financial.amount(raw) == want


def test_zero_is_kept_but_blank_is_not() -> None:
    """0원과 「기재 없음」은 다르다."""
    assert financial.amount("0") == 0
    assert financial.amount("") is None


def test_change_pct_is_none_when_the_base_is_zero_or_missing() -> None:
    """전기가 0이면 증가율이 무한대다 — 없는 숫자를 만들지 않는다."""
    assert financial.change(100, 0, "제 1 기") is not None
    c = financial.change(100, 0, "제 1 기")
    assert c is not None and c.pct is None
    assert financial.change(100, None, "제 1 기") is not None
    assert financial.change(None, 100, "제 1 기") is None  # 당기가 없으면 사실이 없다


def test_negative_base_gives_no_percentage() -> None:
    """적자에서 흑자로 간 것을 「-250% 성장」이라고 적을 수는 없다."""
    c = financial.change(100, -200, "제 1 기")
    assert c is not None
    assert c.now == 100 and c.prev == -200
    assert c.pct is None
    assert c.turned_positive is True


# ── 자본잠식 ──────────────────────────────────────────────────────


def test_no_debt_ratio_when_equity_is_wiped_out() -> None:
    """자본총계가 0 이하면 부채비율이 음수로 나와 오해를 부른다 — 비우고 그렇다고 적는다."""
    items = tuple(
        {**x, "thstrm_amount": "-500,000"} if x["account_nm"] == "자본총계" else x
        for x in accounts(GEN).items
    )
    f = financial.read(Accounts(GEN, HALF, items))
    assert f.debt_ratio is None
    assert "부채비율" in f.absent
    assert f.equity_wiped_out is True


def test_zero_equity_is_also_wiped_out() -> None:
    items = tuple(
        {**x, "thstrm_amount": "0"} if x["account_nm"] == "자본총계" else x
        for x in accounts(GEN).items
    )
    f = financial.read(Accounts(GEN, HALF, items))
    assert f.debt_ratio is None
    assert f.equity_wiped_out is True


def test_healthy_equity_is_not_flagged() -> None:
    assert financial.read(accounts(GEN)).equity_wiped_out is False


# ── 문구 (N1·N2) ─────────────────────────────────────────────────


def test_summary_lines_carry_no_forbidden_words() -> None:
    from verify import wording

    for corp in (GEN, FIN):
        for line in financial.read(accounts(corp)).lines():
            assert not wording.has_forbidden(line), line
            assert not wording.has_forbidden_outcome(line), line


def test_absent_facts_are_said_out_loud_not_dropped() -> None:
    """「비우고 그렇다고 적는다」 — 줄이 통째로 사라지면 안 본 것과 구별되지 않는다."""
    lines = financial.read(accounts(FIN)).lines()
    assert any("매출액" in ln for ln in lines)
    assert any("없" in ln or "비어" in ln for ln in lines)
