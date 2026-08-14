import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@tempest/shared-schema"],
};

export default nextConfig;
