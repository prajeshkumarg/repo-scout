import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle so the runtime image carries the
  // server and its dependencies, not the whole node_modules tree.
  output: "standalone",

  // Next blocks cross-origin requests to dev assets by default, which
  // silently breaks the app when it is opened over a LAN address: the JS
  // chunks 403, nothing hydrates, and no button works. allowedDevOrigins
  // takes hostnames with glob wildcards (not CIDR ranges), so the private
  // IPv4 ranges are listed as patterns. Dev server only.
  allowedDevOrigins: [
    "192.168.*.*",
    "10.*.*.*",
    "172.16.*.*",
    "172.17.*.*",
    "172.18.*.*",
    "172.19.*.*",
    "172.2*.*.*",
    "172.30.*.*",
    "172.31.*.*",
  ],
};

export default nextConfig;
