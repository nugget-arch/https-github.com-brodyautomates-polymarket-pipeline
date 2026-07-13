import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { KillSwitch } from "@/components/KillSwitch";
import { Providers } from "@/components/Providers";

export const metadata: Metadata = {
  title: "cryptoption-quant-bot",
  description: "Research/paper/shadow only. No real-money execution.",
};

const NAV = [
  ["/dashboard", "Dashboard"],
  ["/trading", "Trading"],
  ["/signals", "Señales"],
  ["/history", "Historial"],
  ["/analytics", "Analytics"],
  ["/experiments", "Experimentos"],
  ["/risk", "Riesgo"],
  ["/audit", "Auditoría"],
] as const;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>
        <div className="min-h-screen">
          <header className="flex items-center justify-between border-b border-border bg-panel px-6 py-3">
            <div className="flex items-center gap-3">
              <span className="text-lg font-bold">cryptoption-quant-bot</span>
              <span className="rounded bg-panel2 px-2 py-0.5 text-xs text-muted">
                PAPER · SHADOW · MANUAL — sin dinero real
              </span>
            </div>
            <KillSwitch />
          </header>
          <div className="flex">
            <nav className="w-48 shrink-0 border-r border-border bg-panel px-3 py-4">
              <ul className="space-y-1 text-sm">
                {NAV.map(([href, label]) => (
                  <li key={href}>
                    <a
                      className="block rounded px-3 py-2 text-muted hover:bg-panel2 hover:text-white"
                      href={href}
                    >
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
            <main className="flex-1 p-6">
              <Providers>{children}</Providers>
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
