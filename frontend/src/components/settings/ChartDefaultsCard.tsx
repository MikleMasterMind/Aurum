import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Select } from "@/components/ui/Input";
import { cryptoRangeOptions } from "@/components/crypto/CryptoRangeSelector";
import { netWorthRangeOptions } from "@/components/layout/RangeSelector";
import { useAppSettings, useUpdateAppSettings } from "@/hooks/useSettings";
import { RANGE_PRESET_OPTIONS } from "@/lib/dateRange";
import { useTranslation } from "@/lib/i18n";
import type { RangePreset } from "@/lib/dateRange";

interface ChartDefaultRowProps<T extends string> {
  label: string;
  value: T;
  options: Array<{ value: T; label: string }>;
  disabled: boolean;
  onSelect: (value: T) => void;
}

/** One chart row: a label above a Select, so the card reads the same on
 * mobile (stacked) and desktop. Generic over the period union so the
 * onSelect callback stays fully typed — the cast inside the Select's
 * onChange is the single place a browser-provided string becomes a
 * validated period. */
function ChartDefaultRow<T extends string>({ label, value, options, disabled, onSelect }: ChartDefaultRowProps<T>) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">{label}</p>
      <Select
        value={value}
        disabled={disabled}
        onChange={(event) => {
          // Re-picking the shown option is a no-op — skip the PATCH (the
          // same "unchanged → don't mutate" guard as AlertThresholdsCard).
          const next = event.target.value as T;
          if (next !== value) onSelect(next);
        }}
        className="mt-2 max-w-xs"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>
    </div>
  );
}

/** Which period each page's chart opens with — one row per charted page,
 * saved through the same partial-PATCH as CurrencyCard (no "Save" button
 * for a one-field change). The option lists ARE the pages' own pill lists
 * (exported by the selector components and lib/dateRange.ts), so what you
 * pick here is exactly what you'll see there — they can't drift apart. */
export function ChartDefaultsCard() {
  const { t } = useTranslation();
  const { data: settings, isLoading } = useAppSettings();
  const updateSettings = useUpdateAppSettings();

  const isBusy = isLoading || updateSettings.isPending;
  // The same fallbacks the pages use while the settings response is in
  // flight — the Select is disabled then anyway, this keeps it non-empty.
  const dateRangeOptions: Array<{ value: Exclude<RangePreset, "custom">; label: string }> = RANGE_PRESET_OPTIONS.map(
    ({ value, labelKey }) => ({ value, label: t(labelKey) })
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.chartDefaults")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <p className="text-xs text-text-muted">{t("settings.chartDefaultsHint")}</p>
        <ChartDefaultRow
          label={t("nav.netWorth")}
          value={settings?.default_net_worth_range ?? "5y"}
          options={netWorthRangeOptions(t("common.allShort"))}
          disabled={isBusy}
          onSelect={(value) => updateSettings.mutate({ default_net_worth_range: value })}
        />
        <ChartDefaultRow
          label={t("nav.cashFlow")}
          value={settings?.default_cash_flow_range ?? "this_year"}
          options={dateRangeOptions}
          disabled={isBusy}
          onSelect={(value) => updateSettings.mutate({ default_cash_flow_range: value })}
        />
        <ChartDefaultRow
          label={t("nav.reports")}
          value={settings?.default_reports_range ?? "all"}
          options={dateRangeOptions}
          disabled={isBusy}
          onSelect={(value) => updateSettings.mutate({ default_reports_range: value })}
        />
        <ChartDefaultRow
          label={t("nav.crypto")}
          value={settings?.default_crypto_range ?? "all"}
          options={cryptoRangeOptions(t("common.allShort"))}
          disabled={isBusy}
          onSelect={(value) => updateSettings.mutate({ default_crypto_range: value })}
        />
      </CardContent>
    </Card>
  );
}
