import type { Metadata } from "next";
import { Instrument_Sans } from "next/font/google";
import Link from "next/link";

import "./globals.css";

/**
 * One webfont, self-hosted at build time by next/font — no request to Google at
 * runtime, so no third-party connection and no layout shift from a late swap.
 * Instrument Sans earns its place on one property: true tabular figures, which is what
 * makes a column of amounts line up on the decimal point.
 *
 * Machine strings (references, provider ids, event ids) stay on the system mono stack.
 * A second webfont to render sixteen hex characters would be a poor trade.
 */
const sans = Instrument_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "PayOut",
  description: "A mock cross-border payout console.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={sans.variable}>
      <body>
        <header className="masthead">
          <Link href="/" className="masthead__brand">
            PayOut
          </Link>
          <span className="masthead__note">mock payout console</span>
        </header>
        <main className="shell">{children}</main>
      </body>
    </html>
  );
}
