import "server-only";

import { createHmac } from "node:crypto";

/**
 * Sign a payload the way the fake provider would.
 *
 * This exists so the demo can produce a webhook the backend actually accepts, and it
 * lives on the server for one reason: signing requires PROVIDER_WEBHOOK_SECRET, and a
 * secret shipped to a browser is not a secret. If this ran in a client component, the
 * shared key would sit in the JS bundle and anyone could forge a "completed" event —
 * which is the precise attack the signature exists to stop.
 *
 * Returns the body *and* its signature together, deliberately. The one way to get HMAC
 * verification wrong is to sign one representation and send another: serialise twice,
 * or let a layer in between re-encode the JSON, and the bytes the server hashes are no
 * longer the bytes that were signed. Every signature then fails, permanently, for
 * reasons that look like a bad secret. (The backend had exactly this bug — it hashed a
 * re-canonicalised payload instead of the raw request body — and it is the subtle bug
 * written up in the README.) Handing back a single `body` string that the caller must
 * post verbatim makes the mistake structurally hard to repeat.
 */
export function signProviderPayload(payload: object): {
  body: string;
  signature: string;
} {
  const secret =
    process.env.PROVIDER_WEBHOOK_SECRET ?? "dev-webhook-secret-change-me";
  const body = JSON.stringify(payload);
  const digest = createHmac("sha256", secret).update(body, "utf8").digest("hex");
  return { body, signature: `sha256=${digest}` };
}
