import { useEffect, useState } from "react";
import { request } from "./api";

const categories = {
  instructions: "AGENTS.md",
  skill: "Skills",
  tool: "Tools",
  workflow: "Workflows",
};

type Snapshot = {
  revision: string;
  entries: { category: keyof typeof categories; path: string; text: string }[];
};

export function OverlayInventory({ refreshKey }: { refreshKey: number }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void request<Snapshot>("overlay-inventory", undefined, controller.signal)
      .then(value => { setSnapshot(value); setError(false); })
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [refreshKey]);

  return <section className="list-view overlay-inventory">
    <header className="list-view-head"><h1>Overlay inventory</h1></header>
    {error ? <p role="alert">Overlay inventory is unavailable.</p> : snapshot ? <>
      <p>Overlay commit <code>{snapshot.revision}</code></p>
      {(Object.entries(categories) as [keyof typeof categories, string][]).map(([category, label]) => {
        const entries = snapshot.entries.filter(entry => entry.category === category);
        return <section key={category}>
          <h2>{label}</h2>
          {entries.length === 0 ? <p className="muted">No definitions included.</p> : entries.map(entry =>
            <details key={entry.path}>
              <summary>{entry.path}</summary>
              {entry.text.trim() ? <pre>{entry.text}</pre> : <p className="muted">This file is empty.</p>}
            </details>
          )}
        </section>;
      })}
    </> : <p role="status">Loading overlay inventory…</p>}
  </section>;
}
