"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Re-fetch the current route while a transfer is still in flight.
 *
 * A transfer in `processing` is waiting on a provider webhook that this app never
 * sees — it arrives at Django, out of band, at a time nobody can predict. Without
 * something like this, "watch its status update" means "press reload and hope".
 *
 * Polling, and not something cleverer, on purpose. Server-Sent Events or a WebSocket
 * would push the change the moment it lands, but both need the backend to hold and
 * notify connections, and the brief puts background workers and infrastructure
 * explicitly out of scope. Polling costs one cheap read every few seconds, only while
 * a transfer is actually pending or processing, and stops dead once the status is
 * terminal — a completed transfer is never going to change again, so continuing to
 * ask would be pure waste.
 *
 * `router.refresh()` re-runs the server component and reconciles the result into the
 * existing tree, so the page updates without a flash and without losing form state.
 */
export function AutoRefresh({
  enabled,
  intervalMs = 3000,
}: {
  enabled: boolean;
  intervalMs?: number;
}) {
  const router = useRouter();

  useEffect(() => {
    if (!enabled) return;

    const interval = setInterval(() => {
      // Don't poll a tab nobody is looking at; the focus listener below catches up
      // the moment the user returns.
      if (document.visibilityState === "visible") router.refresh();
    }, intervalMs);

    const onVisible = () => {
      if (document.visibilityState === "visible") router.refresh();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, intervalMs, router]);

  return null;
}
