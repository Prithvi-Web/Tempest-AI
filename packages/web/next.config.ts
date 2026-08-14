import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@tempest/shared-schema"],
  // Monorepo root, pinned so file tracing never guesses from stray lockfiles outside the repo.
  outputFileTracingRoot: path.join(__dirname, "../.."),
};

export default nextConfig;
