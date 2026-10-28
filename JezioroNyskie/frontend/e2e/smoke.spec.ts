import { expect, test, type Page } from '@playwright/test';
import { HAS_MODEL } from '../playwright.config';

test.skip(!HAS_MODEL, 'brak data/processed/model/all/ — pomijam testy end-to-end');

// Każdy błąd skryptu na stronie (pageerror) wywala test.
function trackErrors(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  return errors;
}

const SUMMARY = /bezpieczne .*% akwenu/;

test('zmiana zanurzenia przelicza strefy i podsumowanie', async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto('/');
  const summary = page.getByText(SUMMARY).first();
  await expect(summary).toBeVisible();
  const before = await summary.textContent();

  await page.getByRole('button', { name: /Zwiększ zanurzenie/ }).click();
  await expect(page.getByText(SUMMARY).first()).not.toHaveText(before!);
  await expect(page.getByText(SUMMARY).first()).toContainText('1,25');
  expect(errors).toEqual([]);
});

test('klik w wodę otwiera popup z przedziałem głębokości', async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto('/');
  await expect(page.getByText(SUMMARY).first()).toBeVisible();
  const canvas = page.locator('canvas.maplibregl-canvas');
  await expect(canvas).toBeVisible();
  // Środek mapy poza panelem (400 px z lewej) leży nad głównym plesem jeziora.
  const box = (await canvas.boundingBox())!;
  await page.mouse.click(box.x + 400 + (box.width - 424) / 2, box.y + box.height / 2);
  const dialog = page.getByRole('dialog', { name: 'Informacje o punkcie' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(/\d\s?m\b/);
  await expect(dialog).not.toContainText(/NaN|null|Infinity/);
  expect(errors).toEqual([]);
});

test('historia: nałożenie linii i „Ustaw ten poziom na mapie”', async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto('/historia');
  const toggle = page.getByRole('checkbox', { name: /Nałóż linię brzegową/ }).first();
  await expect(toggle).toBeVisible();
  await toggle.check();
  await expect(toggle).toBeChecked();
  await page.getByRole('button', { pressed: false }).filter({ hasText: /\d{2}\.\d{2}\.\d{4}/ }).first().click();
  await page.getByRole('link', { name: 'Ustaw ten poziom na mapie' }).click();
  await expect(page).toHaveURL(/\/\?h=\d+(\.\d+)?/);
  await expect(page.getByText(SUMMARY).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test('stan błędu przy wyłączonym API stref', async ({ page }) => {
  await page.route('**/api/zones*', (r) => r.abort());
  await page.goto('/');
  await expect(page.getByText('Nie udało się przeliczyć stref')).toBeVisible();
});
