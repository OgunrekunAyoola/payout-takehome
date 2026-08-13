"use client";

import { useEffect, useState } from "react";

/**
 * How long we have been waiting — counting up, never down.
 *
 * This is the honest half of the waiting screen. A progress bar is a claim about the
 * future and we have none: the provider's webhook arrives when it arrives, and no ETA
 * exists. What we *can* say is how long it has been, which is true right now and is
 * itself operational information — a wait getting visibly long is what makes someone
 * go and look.
 *
 * Client-only and mount-gated, deliberately. The value derives from the current clock,
 * so a server render and a browser hydration would disagree and React would report a
 * mismatch. Rendering `null` until `useEffect` fires means the server pass and the
 * first client pass produce identical output, and the counter appears a tick later.
 * Every other timestamp on the page stays server-rendered through the pinned-locale
 * UTC formatter.
 */
export function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    const start = Date.now();
    setNow(start);
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, []);

  if (now === null) return null;

  const from = new Date(since).getTime();
  if (Number.isNaN(from)) return null;

  return (
    <span className="numeric" suppressHydrationWarning>
      {formatDuration(Math.max(0, now - from))} elapsed
    </span>
  );
}

function formatDuration(ms: number): string {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hours > 0
    ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`;
}
