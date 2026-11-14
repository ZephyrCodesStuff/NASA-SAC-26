import type { Metadata } from "next";
import { Fraunces, Geist_Mono, Lexend } from "next/font/google";
import { Toaster } from "sonner";
import { AuthProvider } from "@/lib/auth-context";
import "./globals.css";

const lexendSans = Lexend({
  variable: "--font-lexend-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "NASA Space Apps 2026 — Crop Rotation Planner",
  description: "Resilient 3-year crop rotation decision support powered by NASA Earth observations & Catasto.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${lexendSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-[#faf9f5] text-[#1f1915]">
        <AuthProvider>{children}</AuthProvider>
        <Toaster position="bottom-right" richColors />
      </body>
    </html>
  );
}
