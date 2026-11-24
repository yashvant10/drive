import type { NextConfig } from "next";

const config: NextConfig = {
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
    ] }];
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: (process.env.API_URL ?? "http://127.0.0.1:8000") + "/api/v1/:path*" }];
  },
};
export default config;
