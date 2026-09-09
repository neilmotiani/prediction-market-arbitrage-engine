import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Prediction Market Arbitrage Engine",
  description:
    "Depth-aware prediction market research, execution analysis, and paper trading.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
