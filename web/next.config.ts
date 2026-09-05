import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 검색 엔진에 안 잡힌다 (F55). 페이지 metadata의 robots와 이중이다.
  async headers() {
    return [{ source: "/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }];
  },
};

export default nextConfig;
