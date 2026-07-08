import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
const inter = Inter({ subsets: ["latin"] });

import { Toaster } from "react-hot-toast";
import PageTransition from "@/components/page-transition";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "invid.ai - AI-Powered Social Media Growth Platform",
  description:
    "Transform your social media presence with AI-powered content creation. Generate viral titles, engaging descriptions, and trending hashtags that maximize reach and engagement across all platforms.",

  // Enhanced SEO
  keywords: [
    "AI content generator",
    "social media growth",
    "content as a service",
    "viral content",
    "social media marketing",
    "AI SaaS",
    "hashtag generator",
    "SEO optimization",
    "YouTube growth",
    "Instagram marketing",
    "TikTok content",
  ],

  // Open Graph / Social Sharing
  openGraph: {
    title: "invid.ai - AI-Powered Social Media Growth Platform",
    description:
      "Generate content that gets more reach, likes, and shares with our AI-powered platform. Join 100+ creators already growing their audience.",
    url: "https://socializer-gamma.vercel.app/",
    siteName: "invid.ai",
    images: [
      {
        url: "/logo.png",
        width: 1200,
        height: 630,
        alt: "invid.ai - Social Media Growth Platform",
      },
    ],
    locale: "en_US",
    type: "website",
  },

  // Twitter Card
  twitter: {
    card: "summary_large_image",
    title: "invid.ai - AI-Powered Social Media Growth Platform",
    description:
      "Generate content that gets more reach, likes, and shares with our AI-powered platform.",
    images: ["/logo.png"],
  },

  // Additional Metadata
  metadataBase: new URL("https://socializer-gamma.vercel.app"),
  alternates: {
    canonical: "/",
  },
  icons: {
    icon: [
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
    shortcut: "/favicon.ico",
  },
  manifest: "/site.webmanifest",
  category: "technology",
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="scroll-smooth">
      <head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />

        {/* PWA Meta Tags */}
        <meta name="application-name" content="invid.ai" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta
          name="apple-mobile-web-app-status-bar-style"
          content="black-translucent"
        />
        <meta name="apple-mobile-web-app-title" content="invid.ai" />
        <meta name="format-detection" content="telephone=no" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="theme-color" content="#9333EA" />

        {/* Microsoft Tiles */}
        <meta name="msapplication-config" content="/browserconfig.xml" />
        <meta name="msapplication-TileColor" content="#9333EA" />
        <meta name="msapplication-tap-highlight" content="no" />

        {/* Fonts */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
      </head>
      <body className={`${inter.className} antialiased`}>
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            style: {
              background: "rgba(255, 255, 255, 0.1)",
              backdropFilter: "blur(10px)",
              border: "1px solid rgba(255, 255, 255, 0.2)",
              color: "#fff",
              borderRadius: "12px",
            },
            success: {
              iconTheme: {
                primary: "#10B981",
                secondary: "#fff",
              },
            },
            error: {
              iconTheme: {
                primary: "#EF4444",
                secondary: "#fff",
              },
            },
          }}
        />
        <Providers>
          <PageTransition>{children}</PageTransition>
        </Providers>
      </body>
    </html>
  );
}
