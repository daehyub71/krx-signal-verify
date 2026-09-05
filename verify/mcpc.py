"""MCP stdio 클라이언트 — 남이 만든 MCP 서버를 배치의 데이터 소스로 부른다 (SPEC N5·F34).

**MCP 서버는 데이터 소스다.** 도구 호출 순서·인자는 코드가 정하고, LLM에는 도구를 주지 않는다.

구조:
- 서버마다 **전용 이벤트 루프 스레드** 하나. 그 위에서 `npx -y <pkg>@<버전>`을 stdio로 띄우고
  `ClientSession`을 배치당 **1회** 열어 둔다 — 호출마다 프로세스를 띄우지 않는다.
- 노드(LangGraph `Send` fan-out은 스레드 병렬)는 동기 `call()`로 부른다. **락으로 직렬화**한다 —
  세션 하나에 동시에 닿으면 stdio 프레임이 섞인다.
- 실패는 넷으로 나눈다. 호출자는 종목 단위로 격리한다 (F34 — 그 갈래만 비우고 판정은 나간다).

| 예외 | 뜻 | 서버 상태 |
|------|-----|----------|
| `McpStartError` | 자격증명 없음 · npx 실패 · 서버 자멸 · 대기 초과 | 죽음 (다시 안 띄운다) |
| `McpCallError` | 도구가 `is_error`로 답함 · 없는 도구 · 타임아웃 · JSON 아님 | 살아 있음 |
| `McpProtocolError` | 세션 파손 — stdout 오염·파이프 끊김 | 죽음 — 이후 즉시 Unavailable |
| `McpUnavailableError` | 안 떴거나 죽은 서버를 부름 | — |

MCP 파이썬 SDK 2.x는 응답 필드가 snake_case다 (`tool.input_schema`, `result.is_error`) —
1.x 문서와 다르다.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError as SdkMcpError

# 서버 프로세스에 항상 넘기는 환경변수.
# npx를 찾으려면 PATH가, 캐시(~/.korean-dart-mcp 등)를 두려면 HOME이 필요하다.
BASE_ENV = ("PATH", "HOME")

DEFAULT_TIMEOUT = 30.0

# 기동 대기 상한. 실측(2026-09-02, **빈 npm 캐시** = CI 조건):
#   korean-dart-mcp 12.3초 · naver-search-mcp 3.0초 (더운 캐시로는 3.3초 · 0.6초).
# 가장 느린 것의 다섯 배 이상으로 둔다 — CI 러너는 회선·디스크가 느리다.
# 서버를 더하면서 이 값을 안 올리면 test_start_timeout_clears_the_slowest_cold_start_with_room이
# 먼저 깨진다. 그리고 **스스로 죽는 서버는 이 상한에 걸리지 않는다** — 예외가 곧장 올라오므로,
# 여유를 크게 두어도 흔한 실패에서 손해가 없다. 이 상한은 진짜 매달림에만 쓰인다.
START_TIMEOUT = 90.0


@dataclass(frozen=True, slots=True)
class Spec:
    """MCP 서버 정의. **버전은 고정한다** (N5) — 범위 기호가 끼면 어제와 다른 서버가 뜬다."""

    name: str
    package: str
    version: str  # 정확한 x.y.z. `^`·`~`·`latest` 금지 (테스트가 막는다)
    cold_start_seconds: float  # 잰 값. 추측을 넣지 않는다 — 0이면 아무도 안 쟀다는 뜻이다
    env: tuple[str, ...] = ()  # 서버 프로세스에 넘길 환경변수 (있는 것만)
    # 자격증명 **쌍** 목록 — 하나라도 온전하면 띄운다. 반쪽이면 서버가 스스로 죽으므로 미리 거른다.
    credentials: tuple[tuple[str, ...], ...] = ()

    def missing_credentials(self) -> list[str]:
        """온전한 쌍이 하나도 없으면 첫 쌍의 빠진 이름들을 돌려준다. 있으면 빈 목록.

        값이 **빈 문자열이면 없는 것으로 센다** — `.env`에 이름만 남은 줄이 흔하다.
        """
        if not self.credentials:
            return []
        gaps = [[k for k in pair if not os.environ.get(k, "").strip()] for pair in self.credentials]
        return [] if any(not g for g in gaps) else gaps[0]


# 2026-09-02 기동 실측 버전 — 둘 다 그날의 npm 최신과 같다.
# 올릴 때는 계약 테스트(표본 JSON)를 다시 돌린다.
#
# ⚠ **korean-dart-mcp의 배너를 믿지 마라.** 0.10.1을 받아도 서버는 stderr에 「v0.9.2 stdio 서버
# 시작」이라고 찍는다 — 상류가 build/version.js를 안 올렸다(2026-09-02 확인:
# package.json·npx 캐시·레지스트리 tarball 모두 0.10.1). 배너를 보고 고정이 안 먹었다고
# 판단하면 안 된다. 실제로 무엇이 깔렸는지는 npx 캐시의 package.json으로 본다.
#
# korea-stock-mcp는 **배치에 넣지 않는다** (선행 D14 v2): 시총·상장주식수는 상위 krx-stock-charts가
# pykrx로 ksc_tickers에 채우고 우리는 SQL로 읽는다 — 키도 호출도 0이다. 콜드스타트만 늘어난다.
SERVERS: dict[str, Spec] = {
    "dart": Spec(
        name="dart",
        package="korean-dart-mcp",
        version="0.10.1",
        cold_start_seconds=12.3,
        env=("DART_API_KEY",),
        credentials=(("DART_API_KEY",),),
    ),
    "naver": Spec(
        name="naver",
        package="@isnow890/naver-search-mcp",
        version="1.0.50",
        cold_start_seconds=3.0,
        # 어느 쌍이 올지 모르니 넷을 다 넘긴다 (서버가 HUB 쌍을 우선한다)
        env=(
            "NCP_APIGW_API_KEY_ID",
            "NCP_APIGW_API_KEY",
            "NAVER_CLIENT_ID",
            "NAVER_CLIENT_SECRET",
        ),
        # 키가 없거나 반쪽이면 서버가 기동 자체를 거부한다(실측).
        # HUB 쌍(권장) 또는 개발자센터 쌍(2027-06-30 종료) 중 **하나만** 온전하면 된다.
        credentials=(
            ("NCP_APIGW_API_KEY_ID", "NCP_APIGW_API_KEY"),
            ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"),
        ),
    ),
}


class McpError(RuntimeError):
    """MCP 계층의 모든 실패."""


class McpStartError(McpError):
    """서버를 띄우지 못했다."""


class McpCallError(McpError):
    """도구 호출이 실패했다 — 서버는 살아 있다."""


class McpProtocolError(McpError):
    """세션이 파손됐다 — 서버를 죽은 것으로 표시한다 (R18)."""


class McpUnavailableError(McpError):
    """안 떴거나 죽은 서버를 불렀다."""


def npx_command(spec: Spec) -> tuple[str, list[str]]:
    """`npx -y <package>@<version>` — 버전 고정."""
    return "npx", ["-y", f"{spec.package}@{spec.version}"]


def env_for(spec: Spec) -> dict[str, str]:
    """서버 프로세스 환경 — 기본 키 + 그 서버가 쓰는 키만. 다른 시크릿은 넘기지 않는다."""
    return {k: os.environ[k] for k in BASE_ENV + spec.env if k in os.environ}


@asynccontextmanager
async def _connector(spec: Spec, env: dict[str, str]) -> AsyncIterator[Any]:
    """실제 SDK 커넥터 — npx stdio 프로세스 + 초기화된 `ClientSession`을 내준다."""
    cmd, args = npx_command(spec)
    params = StdioServerParameters(command=cmd, args=args, env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


Connector = Callable[[Spec, dict[str, str]], Any]


@dataclass
class _Loop:
    """세션을 얹어 둔 전용 이벤트 루프 스레드."""

    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    ready: threading.Event = field(default_factory=threading.Event)
    closed: threading.Event = field(default_factory=threading.Event)
    stop: asyncio.Event | None = None
    error: BaseException | None = None


class McpServer:
    """MCP 서버 하나의 세션. `start()` → `call()`… → `close()`."""

    def __init__(self, spec: Spec, *, connector: Connector | None = None) -> None:
        self.spec = spec
        self._connector: Connector = connector or _connector
        self._lock = threading.Lock()
        self._rt: _Loop | None = None
        self._session: Any = None
        self._tools: list[str] = []
        self._dead: str = ""

    # ── 상태 ────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """호출할 수 있는 상태인가."""
        return self._session is not None and not self._dead

    @property
    def reason(self) -> str:
        """못 쓰는 이유. 빈 문자열이면 아직 안 띄웠거나 멀쩡하다."""
        return self._dead

    @property
    def tools(self) -> list[str]:
        """서버가 내놓은 도구 이름."""
        return list(self._tools)

    # ── 수명 ────────────────────────────────────────────────────

    def start(self, timeout: float = START_TIMEOUT) -> None:
        """세션을 연다. 실패하면 `McpStartError` — 다시 띄우지 않는다.

        자격증명은 **띄우기 전에** 본다. 반쪽 쌍으로 npx를 부르면 서버가 스스로 죽는데,
        그 실패는 콜드스타트만큼 기다린 뒤에야 돌아온다.

        Args:
            timeout: 기동 대기 상한(초). 기본값은 실측 콜드스타트의 다섯 배 이상이다.

        Raises:
            McpStartError: 온전한 자격증명 쌍이 없음 · npx/서버 실패 · 대기 초과.
        """
        missing = self.spec.missing_credentials()
        if missing:
            self._dead = f"환경변수 없음: {', '.join(missing)}"
            raise McpStartError(f"[{self.spec.name}] {self._dead} — 서버를 띄우지 않는다")
        if self._rt is not None:
            return
        loop = asyncio.new_event_loop()
        rt = self._rt = _Loop(
            loop=loop,
            thread=threading.Thread(
                target=loop.run_forever, name=f"mcp-{self.spec.name}", daemon=True
            ),
        )
        rt.thread.start()
        asyncio.run_coroutine_threadsafe(self._run(rt), loop)
        if not rt.ready.wait(timeout):
            self._fail(f"기동 {timeout:.0f}초 초과")
        if rt.error is not None:
            self._fail(f"기동 실패: {rt.error}")
        print(f"[mcp] {self.spec.name} {self.spec.package}@{self.spec.version} "
              f"기동 · 도구 {len(self._tools)}개")

    def _fail(self, why: str) -> None:
        """기동 실패를 적고 루프를 걷어낸 뒤 올린다."""
        self._dead = why
        self._shutdown()
        raise McpStartError(f"[{self.spec.name}] {why}") from None

    async def _run(self, rt: _Loop) -> None:
        """루프 스레드 안에서 세션을 열고, 닫으라는 신호까지 붙들고 있는다."""
        rt.stop = asyncio.Event()
        try:
            async with self._connector(self.spec, env_for(self.spec)) as session:
                self._tools = [t.name for t in (await session.list_tools()).tools]
                self._session = session
                rt.ready.set()
                await rt.stop.wait()
        except BaseException as exc:  # noqa: BLE001 — 기동 실패를 호출 스레드에 그대로 전달한다
            rt.error = exc
            rt.ready.set()
        finally:
            self._session = None
            rt.closed.set()

    def close(self) -> None:
        """세션과 프로세스를 닫는다. 여러 번 불러도 안전하다."""
        rt = self._rt
        if rt is None:
            return
        if rt.stop is not None and self._session is not None:
            rt.loop.call_soon_threadsafe(rt.stop.set)
            rt.closed.wait(10)
        self._shutdown()

    def _shutdown(self) -> None:
        rt, self._rt, self._session = self._rt, None, None
        if rt is None:
            return
        rt.loop.call_soon_threadsafe(rt.loop.stop)
        rt.thread.join(5)

    # ── 호출 ────────────────────────────────────────────────────

    def call(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = DEFAULT_TIMEOUT
    ) -> str:
        """도구를 부르고 텍스트 본문을 돌려준다. 스레드 여럿이 불러도 한 번에 하나만 세션에 닿는다.

        Args:
            tool: 도구 이름.
            args: 도구 인자.
            timeout: 응답 대기 상한(초).

        Returns:
            `text` 콘텐츠를 이어 붙인 문자열 (보통 JSON).

        Raises:
            McpUnavailableError: 안 떴거나 죽은 서버.
            McpCallError: 없는 도구 · `is_error` 응답 · 타임아웃 · 서버 오류 응답.
            McpProtocolError: 세션 파손 — 서버를 죽은 것으로 표시한다.
        """
        with self._lock:
            rt = self._rt
            if not self.available or rt is None:
                why = self._dead or "기동 전"
                raise McpUnavailableError(f"[{self.spec.name}] 사용 불가: {why}")
            if self._tools and tool not in self._tools:
                raise McpCallError(f"[{self.spec.name}] 없는 도구: {tool}")
            fut = asyncio.run_coroutine_threadsafe(
                self._session.call_tool(tool, args, read_timeout_seconds=timeout), rt.loop
            )
            try:
                # SDK read_timeout과 별개로 우리 쪽에도 같은 상한 — 세션이 매달려도 노드는 풀린다
                result = fut.result(timeout)
            except concurrent.futures.TimeoutError:
                fut.cancel()
                raise McpCallError(f"[{self.spec.name}] {tool} 타임아웃 {timeout:.0f}초") from None
            except SdkMcpError as exc:
                raise McpCallError(f"[{self.spec.name}] {tool} 서버 오류: {exc}") from None
            except Exception as exc:  # 프레임 파싱 실패·파이프 끊김 — 세션은 더 못 쓴다
                self._dead = f"{type(exc).__name__}: {exc}"
                raise McpProtocolError(f"[{self.spec.name}] 세션 파손 — {self._dead}") from None
        text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        if getattr(result, "is_error", False):
            raise McpCallError(f"[{self.spec.name}] {tool} 실패: {text[:300]}")
        return text

    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = DEFAULT_TIMEOUT
    ) -> Any:
        """`call()` 결과를 JSON으로 푼다. 서버가 안내문을 평문으로 줄 때가 있다."""
        text = self.call(tool, args, timeout=timeout)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise McpCallError(
                f"[{self.spec.name}] {tool} 응답이 JSON이 아니다: {text[:120]!r}"
            ) from exc


# ── 레지스트리 — 배치당 서버 하나씩 ────────────────────────────────

_servers: dict[str, McpServer] = {}
_registry_lock = threading.Lock()


def get(name: str) -> McpServer:
    """이름으로 서버를 얻는다. 처음 부를 때 띄운다.

    **한 번 실패한 서버는 다시 띄우지 않는다** — 종목마다 재시도하면 44번 콜드스타트를 기다린다.

    Raises:
        McpStartError: 모르는 이름 · 기동 실패 (첫 호출 때, 그리고 이후에도 같은 예외).
    """
    with _registry_lock:
        server = _servers.get(name)
        if server is None:
            spec = SERVERS.get(name)
            if spec is None:
                raise McpStartError(f"모르는 서버: {name} (있는 것: {', '.join(SERVERS)})")
            server = _servers[name] = McpServer(spec)
            server.start()
        elif not server.available:
            raise McpStartError(f"[{name}] 사용 불가: {server.reason or '닫힘'}")
        return server


def close_all() -> None:
    """모든 서버를 닫는다. `main`이 끝날 때 부른다."""
    with _registry_lock:
        for server in _servers.values():
            server.close()
        _servers.clear()
