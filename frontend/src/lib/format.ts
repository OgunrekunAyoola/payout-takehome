import type { Currency } from "./types";

/**
 * Display helpers, shared by server and client components.
 *
 * Both formatters pin an explicit locale and time zone. That is not fussiness: a
 * component rendered on the server and hydrated in the browser must produce the same
 * string in both places, and "whatever locale/zone the runtime happens to have" does
 * not. Left to the defaults, a user in Lagos hydrating a page formatted in the
 * server's zone gets a React hydration mismatch, and the timestamp silently changes
 * after load.
 */

/**
 * Format money without ever turning it into a float.
 *
 * `Intl.NumberFormat` accepts a decimal *string* and formats it at full precision, so
 * the value the backend carefully serialised as a string never passes through a
 * binary float on its way to the screen.
 */
export function formatAmount(amount: string, currency: Currency): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      currencyDisplay: "code",
    }).format(amount as unknown as number);
  } catch {
    // Never let a formatting edge case blank out an amount — showing the raw value is
    // worse-looking and infinitely better than showing nothing.
    return `${currency} ${amount}`;
  }
}

/** Time of day only, for places the date is already established (the custody line's
    segments — the full date lives once, in the facts strip, not five times). */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${new Intl.DateTimeFormat("en-GB", {
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(date)} UTC`;
}

/** UTC everywhere, matching the backend, and labelled so it cannot be misread. */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(date)} UTC`;
}
