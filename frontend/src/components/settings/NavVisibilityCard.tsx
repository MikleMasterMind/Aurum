import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { TOGGLEABLE_NAV } from "@/lib/navigation";
import { useTranslation } from "@/lib/i18n";

interface NavVisibilityCardProps {
  /** Routes currently hidden from the sidebar (subset of TOGGLEABLE_NAV_ROUTES). */
  hiddenRoutes: string[];
  /** `hidden = true` removes the section's menu entry, `false` shows it again. */
  onToggle: (route: string, hidden: boolean) => void;
}

/** Hides optional sidebar sections (whatever navigation.ts's
 * TOGGLEABLE_NAV_ROUTES lists) — a per-browser preference, unlike currency
 * and alert thresholds which are server-persisted. Hiding is menu-only: the
 * pages stay reachable by direct URL, so nothing is lost and the choice is
 * trivially reversible. State/props come from App.tsx, which shares them
 * with the Sidebar. */
export function NavVisibilityCard({ hiddenRoutes, onToggle }: NavVisibilityCardProps) {
  const { t } = useTranslation();

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.navVisibilityTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {TOGGLEABLE_NAV.map((item) => (
            <label
              key={item.to}
              className="flex cursor-pointer select-none items-center gap-3 text-sm text-text-primary"
            >
              <input
                type="checkbox"
                checked={!hiddenRoutes.includes(item.to)}
                onChange={(event) => onToggle(item.to, !event.target.checked)}
                className="h-4 w-4 accent-text-primary"
              />
              {t(item.labelKey)}
            </label>
          ))}
        </div>
        <p className="text-xs text-text-muted">{t("settings.navVisibilityHint")}</p>
      </CardContent>
    </Card>
  );
}
