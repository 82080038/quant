import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Kosmos — Astronacci & Satelit",
  description:
    "Visualisasi alam semesta: tata surya Astronacci + satelit observasi Bumi",
};

/**
 * Layout khusus rute /cosmos — full-screen, TANPA sidebar root.
 * Root layout masih membungkus, tapi halaman cosmos render fixed inset-0
 * yang menutupi sidebar agar tampilan alam semesta memenuhi layar.
 */
export default function CosmosLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
