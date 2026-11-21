import { AlertThresholdsCard } from "@/components/settings/AlertThresholdsCard";
import { BackupCard } from "@/components/settings/BackupCard";
import { ChartDefaultsCard } from "@/components/settings/ChartDefaultsCard";
import { CurrencyCard } from "@/components/settings/CurrencyCard";
import { NavVisibilityCard } from "@/components/settings/NavVisibilityCard";
import { PreferencesCard } from "@/components/settings/PreferencesCard";
import { useAppSettings } from "@/hooks/useSettings";
import { t } from "@/lib/i18n";

interface SettingsPageProps {
  /** Hidden sidebar routes + toggle handler. Owned by App.tsx: the flags are
   * localStorage-backed, the Sidebar needs the very same values, and
   * useLocalStorageState doesn't sync between hook instances. */
  hiddenNavRoutes: string[];
  onToggleNavRoute: (route: string, hidden: boolean) => void;
}

export function SettingsPage({ hiddenNavRoutes, onToggleNavRoute }: SettingsPageProps) {
  // Purely informational — if the settings request hasn't answered yet (or is
  // unreachable), just show nothing rather than a loading/error state for
  // one line of fine print.
  const { data: appSettings } = useAppSettings();

  return (
    <div className="space-y-5">
      {/* Client-side display preferences first: NavVisibilityCard groups with
          PreferencesCard because both are per-browser (localStorage), unlike
          the server-persisted currency and alert thresholds below. */}
      <PreferencesCard />
      <NavVisibilityCard hiddenRoutes={hiddenNavRoutes} onToggle={onToggleNavRoute} />
      <CurrencyCard />
      <ChartDefaultsCard />
      <AlertThresholdsCard />
      <BackupCard />
      {appSettings?.app_version && (
        <p className="text-center text-xs text-text-muted">
          {t("settings.version", { version: appSettings.app_version })}
        </p>
      )}
    </div>
  );
}
