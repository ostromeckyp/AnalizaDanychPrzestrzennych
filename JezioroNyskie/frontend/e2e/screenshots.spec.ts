import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { test, type Page } from '@playwright/test';
import { HAS_MODEL } from '../playwright.config';

// Zrzuty do docs/img: SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts
// MOCKUPS=1 dodatkowo zapisuje zrzuty makiet z docs/design (mockup-*.png).
test.skip(!process.env.SCREENSHOTS || !HAS_MODEL, 'zrzuty tylko z SCREENSHOTS=1 i danymi modelu');

const OUT = resolve(import.meta.dirname, '../../docs/img');
mkdirSync(OUT, { recursive: true });

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };

async function ready(page: Page) {
  await page.getByText(/bezpieczne .*% akwenu/).first().waitFor();
  await page.waitForTimeout(2000); // kafelki i obrazy warstw
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(scheme, () => {
    test.use({ colorScheme: scheme });

    test(`desktop ${scheme}`, async ({ page }) => {
      await page.setViewportSize(DESKTOP);
      await page.goto('/');
      await ready(page);
      await page.screenshot({ path: `${OUT}/m6-desktop-${scheme}.png` });
      const c = (await page.locator('canvas.maplibregl-canvas').boundingBox())!;
      await page.mouse.click(c.x + 400 + (c.width - 424) / 2, c.y + c.height / 2);
      await page.getByRole('dialog').waitFor();
      await page.waitForTimeout(500);
      await page.screenshot({ path: `${OUT}/m6-popup-${scheme}.png` });
    });

    test(`mobile ${scheme}`, async ({ page }) => {
      await page.setViewportSize(MOBILE);
      await page.goto('/');
      await ready(page);
      await page.screenshot({ path: `${OUT}/m6-mobile-${scheme}.png` });
      const handle = page.getByRole('button', { name: /panel|parametr|rozwiń/i }).first();
      if (await handle.count()) {
        await handle.click();
        await page.waitForTimeout(600);
        await page.screenshot({ path: `${OUT}/m6-mobile-sheet-${scheme}.png` });
      }
    });

    test(`historia i metoda ${scheme}`, async ({ page }) => {
      await page.setViewportSize(DESKTOP);
      await page.goto('/historia');
      await page.getByRole('checkbox', { name: /Nałóż linię brzegową/ }).first().waitFor();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `${OUT}/m6-historia-${scheme}.png` });
      await page.goto('/metoda');
      await page.waitForTimeout(1000);
      await page.screenshot({ path: `${OUT}/m6-metoda-${scheme}.png`, fullPage: true });
    });
  });
}

test('zoom 15: szwy między strefami', async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await page.goto('/');
  await ready(page);
  const c = (await page.locator('canvas.maplibregl-canvas').boundingBox())!;
  await page.mouse.move(c.x + 1000, c.y + 640); // brzeg strefy ryzykownej i „zbyt płytkiej”
  for (let i = 0; i < 6; i++) {
    await page.mouse.wheel(0, -300);
    await page.waitForTimeout(150);
  }
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT}/m6-zoom15.png` });
});

test('makiety', async ({ page }) => {
  test.skip(!process.env.MOCKUPS, 'MOCKUPS=1');
  const design = resolve(import.meta.dirname, '../../docs/design');
  const files: [string, { width: number; height: number }][] = [
    ['Main', DESKTOP],
    ['MainDark', DESKTOP],
    ['Mobile', MOBILE],
    ['MobileDark', MOBILE],
    ['MobileSheet', MOBILE],
    ['Popups', DESKTOP],
    ['History', DESKTOP],
    ['Method', DESKTOP],
    ['States', DESKTOP],
  ];
  for (const [f, vp] of files) {
    await page.setViewportSize(vp);
    await page.goto(`file://${design}/${f}.dc.html`);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/mockup-${f}.png`, fullPage: true });
  }
});
