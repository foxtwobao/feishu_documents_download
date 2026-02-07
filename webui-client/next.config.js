/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // API proxy is now handled by app/api/[...path]/route.ts
}

module.exports = nextConfig
