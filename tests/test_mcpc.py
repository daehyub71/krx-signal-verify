"""mcpc — MCP stdio 세션 관리. SDK·Node 없이 가짜 세션으로 검사한다 (N14: 외부 I/O는 전부 mock).

이 파일이 지키는 것 (SPEC N5·F34, 선행 D12·D15·R18 계승):
  · **버전 고정** — `npx -y <pkg>@<정확한 버전>`. 범위 기호가 끼면 어제와 다른 서버가 뜬다
  · **자격증명 쌍 사전 검사** — 반쪽이면 서버가 스스로 죽는다. 띄우기 전에 거른다
  · **콜드스타트 타임아웃 여유** — 실측값이 Spec에 있고, 상한이 그 값을 넉넉히 넘는지 검사한다
  · 세션은 배치당 1회 열고 닫는다 · 스레드 여럿이 불러도 락으로 직렬화한다
  · 실패는 넷으로 나뉘고, 세션 파손은 서버를 죽은 것으로 표시해 이후 즉시 실패한다 (매달리지 않는다)
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from verify import mcpc
from verify.mcpc import (
    SERVERS,
    START_TIMEOUT,
    McpCallError,
    McpProtocolError,
    McpServer,
    McpStartError,
    McpUnavailableError,
    Spec,
)

# ── 가짜 SDK 객체 (mcp 2.x 형태 — snake_case) ─────────────────────


@dataclass
class Text:
    type: str
    text: str


@dataclass
class Result:
    content: list[Text]
    is_error: bool = False


@dataclass
class ToolInfo:
    name: str


@dataclass
class Tools:
    tools: list[ToolInfo]


@dataclass
class FakeSession:
    """`ClientSession` 대역. 호출 기록·동시성 측정·정해진 반응."""

    tools: list[str] = field(default_factory=lambda: ["search_disclosures", "insider_signal"])
    replies: dict[str, Any] = field(default_factory=dict)  # tool → 문자열 | Result | Exception
    delay: float = 0.0
    calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> Tools:
        return Tools([ToolInfo(n) for n in self.tools])

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
    ) -> Result:
        self.calls.append((name, arguments))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            reply = self.replies.get(name, '{"ok": true}')
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, Result):
                return reply
            return Result([Text("text", str(reply))])
        finally:
            self.in_flight -= 1


def connector_for(session: FakeSession, *, fail: Exception | None = None) -> Any:
    """세션을 내주는 가짜 커넥터. `fail`이면 기동 자체가 죽는다. 부른 환경을 적어 둔다."""
    seen: list[dict[str, str]] = []

    @asynccontextmanager
    async def connect(spec: Spec, env: dict[str, str]) -> AsyncIterator[FakeSession]:
        seen.append(env)
        if fail is not None:
            raise fail
        yield session

    connect.seen = seen  # type: ignore[attr-defined]
    return connect


SPEC = Spec(name="fake", package="fake-mcp", version="1.0.0", cold_start_seconds=1.0)


@pytest.fixture
def server() -> Any:
    """시작된 서버를 만드는 공장. 테스트 끝에 전부 닫는다."""
    started: list[McpServer] = []

    def make(session: FakeSession | None = None, spec: Spec = SPEC, **kw: Any) -> McpServer:
        s = McpServer(spec, connector=connector_for(session or FakeSession(), **kw))
        started.append(s)
        return s

    yield make
    for s in started:
        s.close()


# ── ① 버전 고정 (N5) ──────────────────────────────────────────────

RANGE_MARKS = ("^", "~", ">", "<", "=", "*", "x", "X", "latest", "next", " ")


def test_every_pinned_version_is_an_exact_number() -> None:
    """`^1.0` 같은 범위가 끼면 어제와 다른 서버가 뜬다 — 계약 테스트가 무의미해진다."""
    for name, spec in SERVERS.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", spec.version), f"{name}: {spec.version!r}"
        assert not any(m in spec.version for m in RANGE_MARKS), name


def test_npx_command_carries_the_exact_version() -> None:
    cmd, args = mcpc.npx_command(SERVERS["dart"])
    assert cmd == "npx"
    assert args == ["-y", "korean-dart-mcp@0.10.1"]


def test_pinned_packages_are_the_two_we_decided_on() -> None:
    """D14 v2 — korea-stock-mcp는 배치에서 뺐다. 조용히 돌아오면 콜드스타트가 늘어난다."""
    assert set(SERVERS) == {"dart", "naver"}
    assert SERVERS["dart"].package == "korean-dart-mcp"
    assert SERVERS["naver"].package == "@isnow890/naver-search-mcp"
    assert not any("stock" in s.package for s in SERVERS.values())


# ── ② 자격증명 쌍 사전 검사 ────────────────────────────────────────


def test_dart_needs_its_one_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DART_API_KEY", raising=False)
    assert SERVERS["dart"].missing_credentials() == ["DART_API_KEY"]
    monkeypatch.setenv("DART_API_KEY", "k")
    assert SERVERS["dart"].missing_credentials() == []


def test_naver_accepts_either_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    """HUB 쌍(권장) 또는 개발자센터 쌍(2027-06-30 종료) — **하나만** 온전하면 된다."""
    for k in ("NCP_APIGW_API_KEY_ID", "NCP_APIGW_API_KEY", "NAVER_CLIENT_ID",
              "NAVER_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    naver = SERVERS["naver"]
    assert naver.missing_credentials()  # 둘 다 없다

    monkeypatch.setenv("NAVER_CLIENT_ID", "a")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "b")
    assert naver.missing_credentials() == []  # 구 쌍만으로 충분하다

    monkeypatch.delenv("NAVER_CLIENT_ID")
    monkeypatch.delenv("NAVER_CLIENT_SECRET")
    monkeypatch.setenv("NCP_APIGW_API_KEY_ID", "a")
    monkeypatch.setenv("NCP_APIGW_API_KEY", "b")
    assert naver.missing_credentials() == []  # HUB 쌍만으로도 충분하다


def test_half_a_pair_is_not_a_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    """반쪽이면 서버가 기동 자체를 거부한다(실측) — 우리가 먼저 거른다."""
    for k in ("NCP_APIGW_API_KEY_ID", "NCP_APIGW_API_KEY", "NAVER_CLIENT_ID",
              "NAVER_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NCP_APIGW_API_KEY_ID", "a")  # 짝이 없다
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "b")  # 이쪽도 짝이 없다
    assert SERVERS["naver"].missing_credentials()


def test_blank_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env`에 키 이름만 남고 값이 빈 경우 — 있는 것으로 세면 서버가 죽는다."""
    monkeypatch.setenv("DART_API_KEY", "   ")
    assert SERVERS["dart"].missing_credentials() == ["DART_API_KEY"]


def test_credentials_are_checked_before_spawning(
    server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검사가 기동 뒤에 있으면 npx를 헛되이 띄운다 — 커넥터가 아예 불리면 안 된다."""
    monkeypatch.delenv("DART_API_KEY", raising=False)
    spec = Spec(
        name="needs", package="p", version="1.0.0", cold_start_seconds=1.0,
        env=("DART_API_KEY",), credentials=(("DART_API_KEY",),),
    )
    s = server(spec=spec)
    with pytest.raises(McpStartError, match="DART_API_KEY"):
        s.start()
    assert s._connector.seen == []  # 띄우지 않았다
    assert not s.available


def test_only_listed_keys_reach_the_server(server: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """다른 시크릿(ANTHROPIC·SUPABASE)을 남의 프로세스에 넘기지 않는다."""
    monkeypatch.setenv("DART_API_KEY", "dart-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    spec = Spec(name="e", package="p", version="1.0.0", cold_start_seconds=1.0,
                env=("DART_API_KEY",))
    s = server(spec=spec)
    s.start()
    env = s._connector.seen[0]
    assert env["DART_API_KEY"] == "dart-key"
    assert "ANTHROPIC_API_KEY" not in env
    assert "PATH" in env  # npx를 찾으려면 필요하다


# ── ③ 콜드스타트 타임아웃 여유 ─────────────────────────────────────


def test_every_spec_records_its_measured_cold_start() -> None:
    """추측이 아니라 잰 값이어야 한다. 0이면 아무도 재지 않았다는 뜻이다."""
    for name, spec in SERVERS.items():
        assert spec.cold_start_seconds > 0, name


def test_start_timeout_clears_the_slowest_cold_start_with_room() -> None:
    """서버를 더할 때 상한을 같이 올리라고 여기서 말해 준다.

    실측(2026-09-02, 빈 npm 캐시): dart 12.3초 · naver 3.0초.
    CI 러너는 캐시가 비어 있고 디스크·회선이 느리다 — 배수로 여유를 둔다.
    """
    slowest = max(s.cold_start_seconds for s in SERVERS.values())
    assert slowest * 5 <= START_TIMEOUT, f"가장 느린 {slowest}초 대비 여유가 부족하다"


def test_start_gives_up_and_marks_dead(server: Any) -> None:
    """매달리지 않는다 — 상한을 넘기면 죽은 것으로 적고 이후 호출은 즉시 실패한다."""
    hang = FakeSession(delay=0)

    @asynccontextmanager
    async def never(spec: Spec, env: dict[str, str]) -> AsyncIterator[FakeSession]:
        await asyncio.sleep(30)
        yield hang

    s = McpServer(SPEC, connector=never)
    with pytest.raises(McpStartError, match="초 초과"):
        s.start(timeout=0.2)
    assert not s.available
    with pytest.raises(McpUnavailableError):
        s.call("search_disclosures")
    s.close()


# ── 세션 수명 ─────────────────────────────────────────────────────


def test_start_opens_the_session_once_and_lists_tools(server: Any) -> None:
    sess = FakeSession(tools=["a", "b"])
    s = server(sess)
    s.start()
    s.start()  # 두 번 불러도 다시 띄우지 않는다
    assert s.available
    assert s.tools == ["a", "b"]
    assert len(s._connector.seen) == 1


def test_close_is_idempotent(server: Any) -> None:
    s = server()
    s.start()
    s.close()
    s.close()
    assert not s.available


def test_call_before_start_fails_fast(server: Any) -> None:
    with pytest.raises(McpUnavailableError, match="기동 전"):
        server().call("search_disclosures")


def test_start_failure_stays_unavailable(server: Any) -> None:
    """서버가 스스로 죽는 경우 — 다시 띄우지 않는다 (F34: 그 갈래만 비운다)."""
    s = server(fail=RuntimeError("npx: not found"))
    with pytest.raises(McpStartError, match="npx"):
        s.start()
    assert not s.available
    assert s.reason


# ── 호출 ─────────────────────────────────────────────────────────


def test_call_returns_text_and_call_json_parses(server: Any) -> None:
    s = server(FakeSession(replies={"search_disclosures": '{"list": [1, 2]}'}))
    s.start()
    assert s.call("search_disclosures") == '{"list": [1, 2]}'
    assert s.call_json("search_disclosures") == {"list": [1, 2]}


def test_non_json_body_is_a_call_error_not_a_crash(server: Any) -> None:
    s = server(FakeSession(replies={"search_disclosures": "서버 점검 중입니다"}))
    s.start()
    with pytest.raises(McpCallError, match="JSON이 아니다"):
        s.call_json("search_disclosures")
    assert s.available  # 서버는 살아 있다


def test_is_error_result_raises_call_error(server: Any) -> None:
    err = Result([Text("text", "한도 초과")], True)
    s = server(FakeSession(replies={"search_disclosures": err}))
    s.start()
    with pytest.raises(McpCallError, match="한도 초과"):
        s.call("search_disclosures")
    assert s.available


def test_unknown_tool_fails_without_touching_the_session(server: Any) -> None:
    sess = FakeSession(tools=["search_disclosures"])
    s = server(sess)
    s.start()
    with pytest.raises(McpCallError, match="없는 도구"):
        s.call("get_financials")
    assert sess.calls == []


def test_timeout_is_a_call_error_and_the_server_survives(server: Any) -> None:
    """도구 하나가 느린 것과 세션이 파손된 것은 다르다 — 종목 단위로만 격리한다."""
    s = server(FakeSession(delay=5))
    s.start()
    with pytest.raises(McpCallError, match="타임아웃"):
        s.call("search_disclosures", timeout=0.15)
    assert s.available


def test_calls_are_serialized_across_threads(server: Any) -> None:
    """`Send` fan-out은 스레드 병렬이다 — 세션 하나에 동시에 닿으면 stdio 프레임이 섞인다."""
    sess = FakeSession(delay=0.05)
    s = server(sess)
    s.start()
    threads = [threading.Thread(target=s.call, args=("search_disclosures",)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sess.calls) == 6
    assert sess.max_in_flight == 1


# ── 세션 파손 격리 (R18) ──────────────────────────────────────────


def test_protocol_error_marks_dead_and_the_next_call_fails_fast(server: Any) -> None:
    """stdout 오염·파이프 끊김. 죽은 서버를 계속 부르면 종목마다 타임아웃만큼 매달린다."""
    sess = FakeSession(replies={"search_disclosures": ValueError("잘린 프레임")})
    s = server(sess)
    s.start()
    with pytest.raises(McpProtocolError, match="세션 파손"):
        s.call("search_disclosures")
    assert not s.available
    with pytest.raises(McpUnavailableError):
        s.call("insider_signal")
    assert len(sess.calls) == 1  # 두 번째는 세션에 닿지도 않았다


def test_one_dead_server_does_not_touch_another(server: Any) -> None:
    """공시가 죽어도 뉴스는 돈다 (F34)."""
    dead = server(FakeSession(replies={"search_disclosures": ValueError("끊김")}))
    alive = server(FakeSession(replies={"search_disclosures": '{"ok": 1}'}))
    dead.start()
    alive.start()
    with pytest.raises(McpProtocolError):
        dead.call("search_disclosures")
    assert not dead.available
    assert alive.available
    assert alive.call("search_disclosures") == '{"ok": 1}'


# ── 레지스트리 ────────────────────────────────────────────────────


def test_registry_starts_lazily_and_reuses(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[Spec] = []

    class Stub(McpServer):
        def start(self, timeout: float = START_TIMEOUT) -> None:
            made.append(self.spec)
            self._session = object()

    monkeypatch.setattr(mcpc, "McpServer", Stub)
    monkeypatch.setattr(mcpc, "_servers", {})
    first = mcpc.get("dart")
    second = mcpc.get("dart")
    assert first is second
    assert len(made) == 1
    mcpc.close_all()
    assert mcpc._servers == {}


def test_registry_does_not_retry_a_failed_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """한 번 실패한 서버를 종목마다 다시 띄우면 44번 콜드스타트를 기다린다."""
    attempts = []

    class Stub(McpServer):
        def start(self, timeout: float = START_TIMEOUT) -> None:
            attempts.append(1)
            self._dead = "npx 실패"
            raise McpStartError("[dart] npx 실패")

    monkeypatch.setattr(mcpc, "McpServer", Stub)
    monkeypatch.setattr(mcpc, "_servers", {})
    with pytest.raises(McpStartError):
        mcpc.get("dart")
    with pytest.raises(McpStartError, match="npx 실패"):
        mcpc.get("dart")
    assert len(attempts) == 1
    mcpc.close_all()


def test_unknown_server_name_is_a_start_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """오타가 KeyError로 튀면 `_guard`가 「errors」로만 적고 원인이 안 보인다."""
    monkeypatch.setattr(mcpc, "_servers", {})
    with pytest.raises(McpStartError, match="모르는 서버"):
        mcpc.get("stock")
