import type { Metadata, Viewport } from "next";
import "./globals.css";
import { TopBar } from "./components/TopBar";
import { Footer } from "./components/Footer";

export const metadata: Metadata = {
  title: "신호 검증 — krx-signal-verify",
  description: "차트 신호가 근거를 갖는지 공시·뉴스·수급·재무로 대조한 판정. 참고용 테스트.",
  // F55 — SSO가 풀리는 날을 대비한 이중 방어. next.config의 X-Robots-Tag와 짝이다.
  robots: { index: false, follow: false, nocache: true },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#eff1f5" },
    { media: "(prefers-color-scheme: dark)", color: "#0d1120" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <TopBar />
        {children}
        <Footer />
      </body>
    </html>
  );
}
