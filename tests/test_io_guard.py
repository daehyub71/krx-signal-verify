"""테스트가 바깥으로 나가지 않는지 지킨다 (N14).

⚠ **이 검사는 원래 `conftest.py`에 있었는데, pytest는 그 파일에서 테스트를 수집하지 않는다** —
평소엔 아예 안 돌고 있었다 (2026-09-05 변이 검사로 드러남). 그래서 여기로 옮겼다.

막는 이유: 그래프 테스트가 신호를 만들고 `judge`가 실물이 되면서 **프로덕션 DB에 두 행을 남겼고**,
`send_email`이 실물이 됐을 때는 **실제 SMTP를 열려 했다.** 둘 다 아무 테스트도 안 깨졌다.
규율로는 못 막는다 — 스텁이 실물이 될 때마다 사람이 기억해야 하기 때문이다.
"""

from __future__ import annotations

from tests.conftest import BLOCKED_SEAMS

# 바깥으로 나가는 호출의 표식. 새 I/O 모듈을 쓰면 여기에 더한다.
OUTWARD = (
    r"store\.connect|notify\.|llm\.|dart\.|dart_mcp\.|news_mcp\.|dart_fin\.|corp\.parse"
)


def test_every_io_seam_is_blocked() -> None:
    """**새 이음매를 목록에 안 넣으면 여기가 깨진다.**

    규율로는 못 막는다 — 스텁이 실물이 될 때마다 사람이 기억해야 하기 때문이다.
    `nodes.py`에서 바깥(DB·SMTP·LLM)을 부르는 `_` 함수를 세어 목록과 대조한다.
    """
    import inspect
    import re

    from verify import nodes

    src = inspect.getsource(nodes)
    bodies = re.split(r"^def ", src, flags=re.M)[1:]
    outward = {
        b.split("(", 1)[0]
        for b in bodies
        if b.startswith("_")
        and re.search(OUTWARD, b)
    }
    missing = outward - set(BLOCKED_SEAMS)
    assert not missing, f"conftest의 BLOCKED_SEAMS에 없다: {missing}"
