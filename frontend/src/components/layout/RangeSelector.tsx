import { PillSelector } from "@/components/layout/PillSelector";
import { useTranslation } from "@/lib/i18n";
import type { NetWorthRange } from "@/types";

interface RangeSelectorProps {
  value: NetWorthRange;
  onChange: (value: NetWorthRange) => void;
}

/** The Net Worth chart's pills, in display order. Exported so the
 * Settings → chart periods card offers exactly the same choices the chart
 * itself does — one list, two consumers, they can't drift apart. Takes
 * the translated "all" label since only the caller knows the language. */
export function netWorthRangeOptions(allLabel: string): Array<{ value: NetWorthRange; label: string }> {
  return [
    { value: "30d", label: "30D" },
    { value: "90d", label: "90D" },
    { value: "1y", label: "1Y" },
    { value: "5y", label: "5Y" },
    { value: "all", label: allLabel },
  ];
}

export function RangeSelector({ value, onChange }: RangeSelectorProps) {
  const { t } = useTranslation();
  return <PillSelector options={netWorthRangeOptions(t("common.allShort"))} value={value} onChange={onChange} />;
}
