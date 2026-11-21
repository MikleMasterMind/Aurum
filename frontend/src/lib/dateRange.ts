/** Shared by CashFlowPage and ReportsPage — both offer the same four
 * period presets over their respective date-ranged endpoints. */
export type RangePreset = "all" | "this_year" | "5y" | "custom";

export interface CustomYearRange {
  fromYear: number;
  toYear: number;
}

/** The three storable presets with their i18n keys, in display order —
 * the single list CashFlowPage's and ReportsPage's pills and the
 * Settings → chart periods card all build from, so the three can't drift
 * apart. "custom" deliberately isn't here: it needs the years picked live
 * on the page, so the pages append it themselves and the settings card
 * (which can only store a period that shows data on open) never offers it.
 * `as const` keeps the label keys literal so they typecheck against the
 * i18n dictionary at the call sites. */
export const RANGE_PRESET_OPTIONS = [
  { value: "all", labelKey: "reports.rangeAll" },
  { value: "this_year", labelKey: "reports.rangeThisYear" },
  { value: "5y", labelKey: "reports.range5y" },
] as const;

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function computeRange(
  preset: RangePreset,
  custom?: CustomYearRange
): { startDate?: string; endDate?: string } {
  const today = new Date();
  switch (preset) {
    case "all":
      return {};
    case "this_year":
      return { startDate: `${today.getFullYear()}-01-01`, endDate: isoDate(today) };
    case "5y": {
      const start = new Date(today.getFullYear() - 5, today.getMonth(), 1);
      return { startDate: isoDate(start), endDate: isoDate(today) };
    }
    case "custom": {
      if (!custom) return {};
      return { startDate: `${custom.fromYear}-01-01`, endDate: `${custom.toYear}-12-31` };
    }
  }
}
