import Link from "next/link";
import { OnDemand } from "./OnDemand";

/** 상단 바 — 모든 화면. 최상위는 셋(오늘·이력·분별력), 온디맨드 입력은 여기 하나다 (DESIGN §1). */
export function TopBar() {
  return (
    <header className="sticky top-0 z-10 flex h-14 items-center gap-7 border-b border-line bg-surface px-8">
      <Link href="/" className="text-[15px] font-bold text-ink no-underline">
        신호 검증
      </Link>
      <nav className="flex gap-5 text-sm font-medium">
        <Link href="/" className="text-ink-2 no-underline hover:text-ink">오늘</Link>
        <Link href="/history" className="text-ink-2 no-underline hover:text-ink">이력</Link>
        <Link href="/discrimination" className="text-ink-2 no-underline hover:text-ink">분별력</Link>
      </nav>
      <div className="grow" />
      <OnDemand />
    </header>
  );
}
