import type { NextConfig } from "next";

let apiUrl =
  process.env.API_URL ||
  (process.env.API_HOST ? `https://${process.env.API_HOST}` : "http://localhost:8001");

// Ensure the URL has a protocol (Vercel env vars sometimes omit https://)
if (apiUrl && !apiUrl.startsWith("http://") && !apiUrl.startsWith("https://")) {
  apiUrl = `https://${apiUrl}`;
}

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
