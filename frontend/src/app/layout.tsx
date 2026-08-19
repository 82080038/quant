import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { MarketProvider } from "@/components/market-context";
import { SchedulerProvider } from "@/components/scheduler-context";
import { ObservabilityProvider } from "@/components/observability-context";
import { CelestialBg } from "@/components/celestial-bg";
import { PageContainer } from "@/components/page-container";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Market — Decision Support",
  description: "Aplikasi decision-support pasar modal Indonesia",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id">
      <body className={inter.className}>
        {/* Astronacci celestial background — fixed, behind everything. */}
        <CelestialBg />
        <MarketProvider>
          <SchedulerProvider>
            <ObservabilityProvider>
              {/* Locked viewport: no page-level scroll. Each route manages
                  its own scroll via PageContainer. */}
              <div className="relative flex h-screen overflow-hidden z-10">
                <Sidebar />
                <div className="flex-1 flex flex-col overflow-hidden">
                  <Header />
                  <main className="flex-1 overflow-hidden">
                    <PageContainer>{children}</PageContainer>
                  </main>
                </div>
              </div>
            </ObservabilityProvider>
          </SchedulerProvider>
        </MarketProvider>
      </body>
    </html>
  );
}
