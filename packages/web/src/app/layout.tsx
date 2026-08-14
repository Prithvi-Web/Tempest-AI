import type { Metadata } from "next";

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
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
