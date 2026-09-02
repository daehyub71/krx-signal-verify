"""선행 `krx-signal-briefing`의 판정을 **골든 파일로 굳힌다** (V11 대조).

이식이 같은 판정을 내는지 보려면 선행을 돌려야 하는데, CI에는 선행 리포가 없다.
그래서 **한 번 받아 적어 두고** `tests/test_parity.py`가 그것과 대조한다.

```bash
python scripts/capture_parity.py           # tests/fixtures/parity_briefing.json 갱신
```

선행 규칙표를 고친 뒤에만 다시 돌린다. **이 파일이 바뀌면 이식이 갈라졌다는 뜻이다.**
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIBLING = ROOT.parent / "krx-signal-briefing"
OUT = ROOT / "tests" / "fixtures" / "parity_briefing.json"
TITLES = ROOT / "tests" / "fixtures" / "report_names.txt"

# 선행 venv 안에서 도는 코드. 우리 코드를 import하지 않는다 — 그러면 대조가 아니다.
PROBE = """
import json, pathlib, sys
sys.path.insert(0, {sibling!r})
from briefing.flags import match, normalize, classify, is_reit
from briefing.routine import is_routine
from briefing.models import Disclosure
from datetime import date

titles = json.loads(pathlib.Path({titles!r}).read_text(encoding="utf-8"))
out = []
for t in titles:
    m = match(t)
    # 리츠 예외(D9)는 **종목명이 있어야** 발동한다 — 이름 없이 부르면 그 갈래가 대조에서 빠진다.
    mr = match(t, "신한알파리츠")
    n = normalize(t)
    d = Disclosure(rcept_dt=date(2026, 9, 1), report_nm=t, rcept_no="x1")
    v = classify([d])
    out.append({{
        "title": t,
        "match": None if m is None else [m.rule, m.level, m.subsidiary],
        "match_reit": None if mr is None else [mr.rule, mr.level, mr.subsidiary],
        "norm": [n.name, n.corrected, n.note],
        "routine": is_routine(t),
        "level": v.level,
        "flags": [[f.rule, f.level] for f in v.flags],
    }})
reit = [[nm, is_reit(nm)] for nm in ["신한알파리츠", "삼성전자", "리츠운용"]]
print(json.dumps({{"rows": out, "reit": reit}}, ensure_ascii=False))
"""


def _rule_samples() -> list[str]:
    """`tests/test_flags.py`의 규칙별 양성·음성 표본. 규칙표가 곧 SPEC이므로 여기서 읽는다."""
    import ast

    src = (ROOT / "tests" / "test_flags.py").read_text(encoding="utf-8")
    blk = src.split("SAMPLES: dict[str, tuple[str, str]] = ", 1)[1]
    depth = 0
    for i, ch in enumerate(blk):
        depth += ch == "{"
        depth -= ch == "}"
        if depth == 0:
            blk = blk[: i + 1]
            break
    samples: dict[str, tuple[str, str]] = ast.literal_eval(blk)
    return [t for pair in samples.values() for t in pair if t]


def main() -> int:
    if not SIBLING.is_dir():
        print(f"선행 리포가 없다: {SIBLING}")
        return 1
    titles = [
        ln.split("\t", 1)[1]
        for ln in TITLES.read_text(encoding="utf-8").splitlines()
        if ln and not ln.startswith("#")
    ]
    # 실표본만으로는 **규칙을 다 건드리지 못한다** — `교환사채권발행결정`·`상장폐지사유해소`가
    # 352종에 없어서, 그 규칙을 지워도 대조가 통과했다 (2026-09-02 변이 검사).
    # 규칙마다 양성·음성 표본을 함께 넣어 **모든 규칙이 대조 대상이 되게** 한다.
    titles += _rule_samples()
    titles = list(dict.fromkeys(titles))  # 순서 유지 중복 제거
    tmp = ROOT / "tests" / "fixtures" / "_titles.json"
    tmp.write_text(json.dumps(titles, ensure_ascii=False), encoding="utf-8")
    try:
        r = subprocess.run(
            [str(SIBLING / "venv" / "bin" / "python"), "-c",
             PROBE.format(sibling=str(SIBLING), titles=str(tmp))],
            capture_output=True, text=True,
        )
        if r.returncode:
            print(r.stderr[-800:])
            return 1
        OUT.write_text(r.stdout, encoding="utf-8")
    finally:
        tmp.unlink(missing_ok=True)
    data = json.loads(OUT.read_text(encoding="utf-8"))
    print(f"{OUT.relative_to(ROOT)} — 제목 {len(data['rows'])}종 · {OUT.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
