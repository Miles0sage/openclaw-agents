import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "OpenClaw Dashboard",
  description: "Live job monitoring dashboard with WebSocket and SSE telemetry.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="background-orb background-orb-one" />
        <div className="background-orb background-orb-two" />
        <main className="app-shell">{children}</main>
      </body>
    </html>
  );
}
