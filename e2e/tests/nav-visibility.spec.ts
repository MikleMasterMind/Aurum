import { test, expect, type Page } from "@playwright/test";

// Sidebar section visibility (Settings → «Разделы в меню»): unchecking a
// section removes its entry from the desktop rail and the mobile drawer,
// while the page itself stays reachable by direct URL — that URL is also
// the undo path. Purely a localStorage feature: no fixtures, no seeded data,
// nothing in the shared DB is touched.

// exact: true — getByRole matches names by substring otherwise, and these
// names (the section labels) can appear in more than one link on a page.
const CRYPTO = { name: "Криптовалюта", exact: true } as const;
const ROI = { name: "Доходность", exact: true } as const;

/** The throwaway e2e stack runs without Basic Auth, so a fresh browser
 * context always gets the app's one-time "Authentication not configured"
 * warning (components/auth/NoAuthModal.tsx) rendered over the UI — it has
 * no backdrop-click/Escape way out by design, only this button. Dismissing
 * it once per test unblocks every later click; the acknowledgement
 * persists in the context's localStorage for the rest of the test. */
async function dismissNoAuthWarning(page: Page) {
  const accept = page.getByRole("button", { name: "Я понимаю риски и хочу продолжить", exact: true });
  await expect(accept).toBeVisible();
  await accept.click();
}

test.describe("nav visibility", () => {
  test("hiding crypto removes it from rail and mobile drawer, and survives reload", async ({ page }) => {
    await page.goto("/");
    await dismissNoAuthWarning(page);
    await expect(page.getByRole("link", CRYPTO)).toBeVisible();

    // The settings page still shows the desktop rail — the entry must
    // disappear there immediately, without a navigation round-trip.
    await page.goto("/settings");
    await page.getByRole("checkbox", CRYPTO).uncheck();
    await expect(page.getByRole("link", CRYPTO)).toHaveCount(0);
    // The neighbouring toggleable section is untouched.
    await expect(page.getByRole("link", ROI)).toBeVisible();

    await page.goto("/");
    await expect(page.getByRole("link", CRYPTO)).toHaveCount(0);

    await page.reload();
    await expect(page.getByRole("link", CRYPTO)).toHaveCount(0);

    // Mobile drawer: narrow viewport, burger button (aria-label from Topbar).
    // Assert on the drawer's close button rather than on a nav link so the
    // check can't be satisfied by anything but the drawer actually opening.
    await page.setViewportSize({ width: 375, height: 700 });
    await page.getByRole("button", { name: "Открыть меню", exact: true }).click();
    await expect(page.getByRole("button", { name: "Закрыть меню", exact: true })).toBeVisible();
    await expect(page.getByRole("link", CRYPTO)).toHaveCount(0);
    await expect(page.getByRole("link", ROI)).toBeVisible();

    // The page itself stays reachable by direct URL — that's the way back.
    await page.goto("/crypto");
    await expect(page).toHaveURL(/\/crypto$/);

    // Checking the box back restores the menu entry. Reset the desktop
    // viewport first: the rail is lg-only, and role locators don't match
    // elements hidden from the accessibility tree — at 375px the restored
    // link would be silently unfindable even though it's in the DOM.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/settings");
    await page.getByRole("checkbox", CRYPTO).check();
    await expect(page.getByRole("link", CRYPTO)).toBeVisible();
  });

  test("hiding both sections keeps the rest of the menu intact", async ({ page }) => {
    await page.goto("/settings");
    await dismissNoAuthWarning(page);
    await page.getByRole("checkbox", CRYPTO).uncheck();
    await page.getByRole("checkbox", ROI).uncheck();

    await page.goto("/");
    await expect(page.getByRole("link", CRYPTO)).toHaveCount(0);
    await expect(page.getByRole("link", ROI)).toHaveCount(0);
    // The non-toggleable core sections are still there.
    await expect(page.getByRole("link", { name: "Дашборд", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Настройки", exact: true })).toBeVisible();
  });
});
