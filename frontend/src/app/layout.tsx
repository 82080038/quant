import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { MarketProvider } from "@/components/market-context";
import { SchedulerProvider } from "@/components/scheduler-context";

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
        <MarketProvider>
          <SchedulerProvider>
            <div className="flex min-h-screen">
              <Sidebar />
              <div className="flex-1 flex flex-col overflow-hidden">
                <Header />
                <main className="flex-1 p-6 overflow-auto">{children}</main>
              </div>
            </div>
          </SchedulerProvider>
        </MarketProvider>
      </body>
    </html>
  );
}
