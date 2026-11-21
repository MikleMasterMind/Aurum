import {
  Activity,
  ArrowLeftRight,
  Bot,
  Calculator,
  Coins,
  Flag,
  Layers,
  Lightbulb,
  LayoutDashboard,
  PieChart,
  Repeat,
  Settings,
  Tags,
  Target,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import type { TranslationKey } from "@/lib/i18n";

export interface NavItem {
  labelKey: TranslationKey;
  to: string;
  icon: LucideIcon;
  disabled?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { labelKey: "nav.dashboard", to: "/", icon: LayoutDashboard },
  { labelKey: "nav.netWorth", to: "/net-worth", icon: TrendingUp },
  { labelKey: "nav.crypto", to: "/crypto", icon: Coins },
  { labelKey: "nav.roi", to: "/roi", icon: Calculator },
  { labelKey: "nav.transactions", to: "/transactions", icon: ArrowLeftRight },
  { labelKey: "nav.accounts", to: "/accounts", icon: Layers },
  { labelKey: "nav.categories", to: "/categories", icon: Tags },
  { labelKey: "nav.cashFlow", to: "/cash-flow", icon: Activity },
  { labelKey: "nav.reports", to: "/reports", icon: PieChart },
  { labelKey: "nav.budget", to: "/budget", icon: Target },
  { labelKey: "nav.recurring", to: "/recurring", icon: Repeat },
  { labelKey: "nav.goals", to: "/goals", icon: Flag },
  { labelKey: "nav.advice", to: "/advice", icon: Lightbulb },
  { labelKey: "nav.assistant", to: "/assistant", icon: Bot },
  { labelKey: "nav.settings", to: "/settings", icon: Settings },
];

/** Sidebar sections the user may hide via Settings — a per-browser preference
 * (localStorage flags in App.tsx), not a server setting. Hiding removes the
 * menu entry only: the routes stay mounted and reachable by direct URL,
 * which is also how the user gets a hidden section back. */
export const TOGGLEABLE_NAV_ROUTES: readonly string[] = ["/crypto", "/roi"];

/** The toggleable entries themselves, in NAV_ITEMS order — the settings card
 * (NavVisibilityCard) maps over these to render one checkbox per section.
 * Labels reuse the existing nav.* translations, so it needs no strings of
 * its own. */
export const TOGGLEABLE_NAV: ReadonlyArray<Pick<NavItem, "to" | "labelKey">> = NAV_ITEMS.filter((item) =>
  TOGGLEABLE_NAV_ROUTES.includes(item.to)
);

/** Pure NAV_ITEMS filter — keeps the original order, drops only the routes
 * listed in hiddenRoutes. Both the desktop rail and the mobile drawer render
 * through it, so a hidden section vanishes from both at once. */
export function visibleNavItems(items: NavItem[], hiddenRoutes: readonly string[]): NavItem[] {
  return items.filter((item) => !hiddenRoutes.includes(item.to));
}
