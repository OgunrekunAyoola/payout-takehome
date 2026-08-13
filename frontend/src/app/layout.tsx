import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

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
    <html lang="en">
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
