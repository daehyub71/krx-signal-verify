# 표면 시안 (DESIGN 합의용)

웹 대시보드 4화면(F51~F54)과 검증 메일(F50)의 시안이다. **M7 착수 전 합의 대상**이다.

> **두 벌이 있다.** 이 디렉토리 바로 아래는 계획 단계(M-1)에 표본 데이터로 그린 초안이고,
> **`web/`가 M7 합의용 정본**이다 — 2026-09-03 실제 판정 값으로 다시 그렸고, 판정 색을 차트 팔레트 검증기에
> 통과시켰으며(정합 `#0F6E5C` → `#0E8A6E`), 온디맨드 화면을 더했다. 합의·결정은 `../DESIGN.md`에 기록한다.
> `web/` 산출물은 `krx-signal-verify-dashboard.html`(`.gitignore`) · 재생성은 아래와 같되 `--out`·`--title`만 다르다.

## 원본과 산출물

| | |
|---|---|
| **원본** | `Main.dc.html`(오늘) · `Stock.dc.html`(종목) · `History.dc.html`(이력) · `Discrimination.dc.html`(분별력) · `Mail.dc.html`(메일) · `canvas.json`(배치) |
| 산출물 | `krx-signal-verify-surfaces.html` — 2.4MB 에디터 페이로드. **커밋하지 않는다** (`.gitignore`) |

고칠 때는 **아트보드(`.dc.html`)를 고치고 다시 만든다.** 산출물을 직접 손대지 않는다.

## 시각 어휘 — 새로 만들지 않고 잇는다

- 색·치수는 `../../krx-signal-alerts/web/app/globals.css` 토큰 (적색 상승·청색 하락 · Pretendard · 52px 행)
- 판정 색은 선행 `krx-signal-briefing` DESIGN G8 — 정합 `#0F6E5C` · 불일치 `#C9283E` · 무관 회색
- 점수 막대 44px (G9) · 메일은 `<table>` 배치만 (G6 — flex·grid는 안드로이드 Gmail에서 무너진다) · 이모지 없음 (G3)

## 데이터는 표본이다

실제 판정이 아니다. 모든 화면에 **「투자 권고가 아닙니다 · 참고용 테스트」**(F55)가 상시로 붙어 있고,
분별력 화면의 60거래일은 **「표본 부족 (n=…)」** 상태 그대로 그렸다 — 소급하지 않기로 했으므로(V13)
실제로 약 3개월간 그 상태다.
