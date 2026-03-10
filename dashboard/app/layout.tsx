import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "OpenClaw Dashboard",
  description: "React dashboard for OpenClaw jobs, costs, and agent performance.",
};

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/jobs", label: "Jobs" },
  { href: "/agents", label: "Agents" },
];

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-slate-100 antialiased">
        <div className="fixed inset-0 bg-dashboard-grid bg-[length:44px_44px] opacity-[0.03]" />
        <div className="fixed inset-x-0 top-[-12rem] h-[28rem] bg-[radial-gradient(circle_at_top,rgba(249,115,22,0.18),transparent_45%)]" />
        <div className="relative mx-auto min-h-screen w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <header className="mb-8 flex flex-col gap-4 rounded-[2rem] border border-white/10 bg-white/[0.03] px-5 py-5 shadow-panel backdrop-blur md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-orange-300">
                OpenClaw
              </p>
              <h1 className="mt-2 text-3xl font-semibold text-white">Operations dashboard</h1>
            </div>
            <nav className="flex flex-wrap gap-2">
              {NAV_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-full border border-white/10 bg-slate-950/70 px-4 py-2 text-sm text-slate-300 transition hover:border-orange-300/40 hover:text-white"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
