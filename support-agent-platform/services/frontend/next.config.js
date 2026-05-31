/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a minimal self-contained server (server.js + trimmed node_modules)
  // so the runtime image stays small and runs as non-root.
  output: "standalone",
};

module.exports = nextConfig;
