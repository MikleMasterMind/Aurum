import { PillSelector } from "@/components/layout/PillSelector";
import { useTranslation } from "@/lib/i18n";
import type { CryptoRange } from "@/types";

interface CryptoRangeSelectorProps {
  value: CryptoRange;
  onChange: (value: CryptoRange) => void;
}

/** The Crypto chart's pills, in display order — exported for the same
 * reason as RangeSelector's list: the Settings → chart periods card
 * reuses it, so the choices there can't drift from the chart's own. */
export function cryptoRangeOptions(allLabel: string): Array<{ value: CryptoRange; label: string }> {
  return [
    { value: "7d", label: "7D" },
    { value: "30d", label: "30D" },
    { value: "90d", label: "90D" },
    { value: "all", label: allLabel },
  ];
}

export function CryptoRangeSelector({ value, onChange }: CryptoRangeSelectorProps) {
  const { t } = useTranslation();
  return <PillSelector options={cryptoRangeOptions(t("common.allShort"))} value={value} onChange={onChange} />;
}
