import type { Stand } from "@/lib/types";

const CLASS: Record<Stand, string> = {
  정합: "chip chip-agree",
  불일치: "chip chip-conflict",
  무관: "chip chip-none",
};

/** 판정 칩. 색과 글자가 함께 간다 — 색만으로 구별하지 않는다. */
export function StandChip({ stand, small = false }: { stand: Stand; small?: boolean }) {
  return (
    <span className={CLASS[stand]} style={small ? { height: 20, fontSize: 11 } : undefined}>
      {stand}
    </span>
  );
}
