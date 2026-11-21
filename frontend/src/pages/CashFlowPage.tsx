import { useState } from "react";
import { PillSelector } from "@/components/layout/PillSelector";
import { YearRangeSelector } from "@/components/layout/YearSelector";
import { CashFlowChart } from "@/components/cashflow/CashFlowChart";
import { useCashFlow } from "@/hooks/useCashFlow";
import { useAppSettings } from "@/hooks/useSettings";
import { useTransactionYears } from "@/hooks/useTransactions";
import { computeRange, RANGE_PRESET_OPTIONS, type CustomYearRange, type RangePreset } from "@/lib/dateRange";
import { useTranslation } from "@/lib/i18n";

export function CashFlowPage() {
  const { t } = useTranslation();
  const now = new Date();
  const { data: years } = useTransactionYears();
  // The opening period is server-configured (Settings → chart periods,
  // seeded to "this_year"); userRange stays null until a pill is picked,
  // so a settings response arriving late can still swap the default in
  // without overriding an explicit choice.
  const { data: appSettings } = useAppSettings();
  const [userRange, setUserRange] = useState<RangePreset | null>(null);
  const range = userRange ?? appSettings?.default_cash_flow_range ?? "this_year";
  const [customRange, setCustomRange] = useState<CustomYearRange>({
    fromYear: now.getFullYear(),
    toYear: now.getFullYear(),
  });

  const RANGE_OPTIONS: Array<{ value: RangePreset; label: string }> = [
    ...RANGE_PRESET_OPTIONS.map(({ value, labelKey }) => ({ value, label: t(labelKey) })),
    { value: "custom", label: t("reports.rangeCustom") },
  ];

  const { startDate, endDate } = computeRange(range, customRange);
  const { data: cashFlow, isLoading } = useCashFlow(startDate, endDate);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <PillSelector options={RANGE_OPTIONS} value={range} onChange={setUserRange} />
        {range === "custom" && (
          <YearRangeSelector
            years={years ?? [now.getFullYear()]}
            fromYear={customRange.fromYear}
            toYear={customRange.toYear}
            onChange={setCustomRange}
          />
        )}
      </div>

      <CashFlowChart cashFlow={cashFlow} isLoading={isLoading} />
    </div>
  );
}
