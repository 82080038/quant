/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["192.168.100.23", "localhost", "127.0.0.1"],
  async rewrites() {
    const apiBase = process.env.API_BASE_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
