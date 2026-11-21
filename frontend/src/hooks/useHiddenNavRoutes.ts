import { useState } from "react";

/** localStorage-backed list of the sidebar routes the user hid in Settings —
 * what qualifies is decided by navigation.ts's TOGGLEABLE_NAV_ROUTES. One
 * JSON array under a single key rather than a key per route: adding a new
 * toggleable section later means no storage-format change. Corrupt or
 * malformed values degrade to "nothing is hidden" instead of crashing the
 * app on boot. Like useLocalStorageState, hook instances don't sync with
 * each other — App owns the single instance and passes the value down. */
const STORAGE_KEY = "aurum:hidden-nav";

function readInitialHiddenRoutes(): string[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === null) return [];
    const parsed: unknown = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed.filter((route): route is string => typeof route === "string") : [];
  } catch {
    return []; // unparsable JSON — behave as if nothing is hidden
  }
}

export function useHiddenNavRoutes() {
  const [hiddenRoutes, setHiddenRoutes] = useState<string[]>(readInitialHiddenRoutes);

  // Write-through, same as useLocalStorageState: React state drives the UI,
  // localStorage makes the choice survive reloads and app restarts.
  function updateHiddenRoutes(next: string[]) {
    setHiddenRoutes(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }

  return [hiddenRoutes, updateHiddenRoutes] as const;
}
