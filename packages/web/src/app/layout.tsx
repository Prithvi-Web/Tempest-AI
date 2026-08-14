import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Tempest AI",
  description: "Behavioral proof agent — evidence, not opinion.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen font-mono antialiased">
        <Providers>
          <header className="border-b border-panel-line">
            <nav
              aria-label="Primary"
              className="mx-auto flex max-w-6xl items-baseline gap-4 px-6 py-3"
            >
              <Link href="/" className="text-sm font-bold tracking-[0.25em] text-ink">
                TEMPEST
              </Link>
              <span className="text-xs text-ink-dim">
                behavioral proof agent · evidence, not opinion
              </span>
            </nav>
          </header>
          {children}
        </Providers>
      </body>
    </html>
  );
}
