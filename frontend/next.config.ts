import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The browser never talks to Django directly — every call goes through a server
  // action or server component in this app (see src/lib/api.ts). That is why the
  // backend needs no CORS configuration, and why PROVIDER_WEBHOOK_SECRET can live
  // here at all without being served to a client bundle.
  //
  // Backend URL is read from the environment at request time, not baked in at build
  // time: BACKEND_URL is deliberately *not* prefixed NEXT_PUBLIC_, which is what keeps
  // it (and the webhook secret beside it) server-side.
  reactStrictMode: true,
};

export default nextConfig;
