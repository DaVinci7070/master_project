import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Increase proxy timeout for long-running operations (sandbox transcription)
  experimental: {
    proxyTimeout: 300000, // 5 minutes
  },
  // API proxy rewrites to backend
  async rewrites() {
    return [
      {
        // Rewrite /api/backend/* to backend's /api/v1/*
        source: "/api/backend/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
