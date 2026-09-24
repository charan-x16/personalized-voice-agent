import { ClerkProvider } from "@clerk/nextjs";
import "@fontsource-variable/instrument-sans";
import "@fontsource-variable/newsreader";
import "@fontsource-variable/newsreader/standard-italic.css";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import { PUBLIC_SITE_URL } from "@/lib/public-site";

const SITE_TITLE = "Svara — Personal voice, real context";
const SITE_DESCRIPTION =
  "A private, multilingual voice-agent platform grounded in the customer data you already trust.";

export const metadata: Metadata = {
  ...(PUBLIC_SITE_URL ? { metadataBase: new URL(PUBLIC_SITE_URL) } : {}),
  title: {
    default: SITE_TITLE,
    template: "%s — Svara",
  },
  description: SITE_DESCRIPTION,
  ...(PUBLIC_SITE_URL ? { alternates: { canonical: "/" } } : {}),
  openGraph: {
    type: "website",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    siteName: "Svara",
  },
  twitter: {
    card: "summary",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
  },
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#f4f1ea",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body>
        <ClerkProvider>{children}</ClerkProvider>
      </body>
    </html>
  );
}
