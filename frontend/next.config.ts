import type { NextConfig } from "next";

const apiUrl =
  process.env.API_URL ||
  (process.env.API_HOST ? `https://${process.env.API_HOST}` : "http://localhost:8001");

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
