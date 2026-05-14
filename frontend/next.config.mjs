const backendUrl = process.env.BACKEND_URL || "http://localhost:5004";
const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
  },
  {
    key: "X-Frame-Options",
    value: "DENY"
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff"
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin"
  }
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["marked"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders
      }
    ];
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      { source: "/prompt_share/api/:path*", destination: `${backendUrl}/prompt_share/api/:path*` },
      { source: "/prompt_manage/api/:path*", destination: `${backendUrl}/prompt_manage/api/:path*` },
      { source: "/search/:path*", destination: `${backendUrl}/search/:path*` },
      { source: "/memo/api/:path*", destination: `${backendUrl}/memo/api/:path*` },
      { source: "/admin/api/:path*", destination: `${backendUrl}/admin/api/:path*` },
      { source: "/admin/logout", destination: `${backendUrl}/admin/logout` },
      { source: "/google-login", destination: `${backendUrl}/google-login` },
      { source: "/google-callback", destination: `${backendUrl}/google-callback` },
      { source: "/logout", destination: `${backendUrl}/logout` }
    ];
  }
};

export default nextConfig;
