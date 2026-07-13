"use client";

import { useState } from "react";

/** Always-visible emergency stop. In Phase 1 it toggles local UI state and
 * will be wired to POST /sessions/{id}/kill-switch in a later phase. */
export function KillSwitch({ engaged: initial = false }: { engaged?: boolean }) {
  const [engaged, setEngaged] = useState(initial);
  return (
    <button
      type="button"
      aria-pressed={engaged}
      onClick={() => setEngaged((v) => !v)}
      className={`rounded-md px-4 py-2 text-sm font-bold uppercase tracking-wide transition-colors ${
        engaged
          ? "bg-neg text-white"
          : "border border-neg text-neg hover:bg-neg hover:text-white"
      }`}
    >
      {engaged ? "■ Detenido" : "● Parada de emergencia"}
    </button>
  );
}
