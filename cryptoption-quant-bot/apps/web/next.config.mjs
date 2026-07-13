/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The web app only talks to our own backend; no external hosts.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};
export default nextConfig;
