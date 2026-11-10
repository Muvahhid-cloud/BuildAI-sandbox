import type { Metadata } from "next";

import { AppHeader } from "@/components/AppHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { themeScript } from "@/lib/theme-script";

// Self-hosted variable font (bundled by Next.js; no runtime CDN).
import "@fontsource-variable/inter";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "BuildAI 3D",
  description: "AI-assisted conceptual design of residential buildings",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-theme is set before first paint by the inline script (hence suppressHydrationWarning).
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="flex h-dvh flex-col overflow-hidden">
        <Providers>
          <AppHeader />
          <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</main>
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}
