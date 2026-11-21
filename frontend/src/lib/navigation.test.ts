import { describe, expect, it } from "vitest";
import { NAV_ITEMS, TOGGLEABLE_NAV_ROUTES, visibleNavItems } from "@/lib/navigation";

describe("visibleNavItems", () => {
  it("returns everything unchanged when nothing is hidden", () => {
    expect(visibleNavItems(NAV_ITEMS, [])).toEqual(NAV_ITEMS);
  });

  it("drops only the hidden routes and keeps the original order", () => {
    const visible = visibleNavItems(NAV_ITEMS, ["/crypto", "/roi"]);
    expect(visible.map((item) => item.to)).not.toContain("/crypto");
    expect(visible.map((item) => item.to)).not.toContain("/roi");
    // Everything else survives, in NAV_ITEMS order.
    expect(visible).toEqual(NAV_ITEMS.filter((item) => item.to !== "/crypto" && item.to !== "/roi"));
  });

  it("ignores routes that are not part of the menu", () => {
    expect(visibleNavItems(NAV_ITEMS, ["/no-such-route"])).toEqual(NAV_ITEMS);
  });
});

describe("TOGGLEABLE_NAV_ROUTES", () => {
  it("advertises only routes that actually exist in NAV_ITEMS (typo guard)", () => {
    const menuRoutes = NAV_ITEMS.map((item) => item.to);
    for (const route of TOGGLEABLE_NAV_ROUTES) {
      expect(menuRoutes).toContain(route);
    }
  });
});
