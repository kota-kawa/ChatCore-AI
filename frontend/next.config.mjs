const backendUrl = process.env.BACKEND_URL || "http://localhost:5004";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["marked"],
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
