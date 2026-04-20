import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    serverActions: {
      // Default is 1 MB. Our upload action forwards multi-file PDFs to the
      // backend — a batch of 4 scanned-PDF fixtures is ~1.5-2 MB, and real
      // title-search documents can run 10-20 MB. 50 MB leaves plenty of headroom.
      bodySizeLimit: "50mb",
    },
  },
};

export default nextConfig;
