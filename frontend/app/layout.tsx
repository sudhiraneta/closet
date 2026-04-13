import type { Metadata } from "next";
import { Playfair_Display, DM_Sans } from "next/font/google";
import "./globals.css";
import { Nav } from "./nav";

const playfair = Playfair_Display({
  variable: "--font-serif",
  subsets: ["latin"],
  display: "swap",
});

const dmSans = DM_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sudhira's Closet",
  description: "A premium digital wardrobe experience",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${playfair.variable} ${dmSans.variable}`}>
      <body className="min-h-screen bg-cream text-charcoal font-sans antialiased">
        {/* Header */}
        <header className="sticky top-0 z-50 bg-cream/80 backdrop-blur-md border-b border-border">
          <div className="max-w-7xl mx-auto px-6 py-5 flex items-center justify-between">
            <h1 className="font-serif text-2xl tracking-tight">
              <a href="/">Sudhira&apos;s Closet</a>
            </h1>
            <Nav />
          </div>
        </header>

        <main className="flex-1">{children}</main>

        {/* Footer */}
        <footer className="border-t border-border mt-20">
          <div className="max-w-7xl mx-auto px-6 py-8 text-center text-sm text-charcoal/40">
            20 pieces &middot; curated with intention
          </div>
        </footer>
      </body>
    </html>
  );
}
