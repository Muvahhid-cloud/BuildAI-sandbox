import type { Metadata } from "next";

import { AppHeader } from "@/components/AppHeader";
import { SiteFooter } from "@/components/SiteFooter";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "BuildAI 3D",
  description: "AI-assisted conceptual design of residential buildings",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
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
