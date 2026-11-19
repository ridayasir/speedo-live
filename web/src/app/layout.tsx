import type { Metadata, Viewport } from "next";
import "./globals.css";
import Shell from "@/components/Shell";
import { AuthProvider } from "@/lib/hooks";

export const metadata: Metadata = {
  title: "Speedo Live",
  description: "Live Speedo bus tracking and route navigation for Lahore. Your Bus, Your Route, Your Time.",
  icons: { icon: "/favicon.svg" },
};

export const viewport: Viewport = { themeColor: "#173693", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <Shell>{children}</Shell>
        </AuthProvider>
      </body>
    </html>
  );
}
