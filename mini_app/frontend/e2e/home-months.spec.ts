import { expect, test } from '@playwright/test';

test.use({ locale: 'ru-RU', hasTouch: true });

test('главная: свайпы меняют месяц и диаграмму', async ({ page }) => {
  await page.route('https://telegram.org/**', route => route.abort());
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/me') return route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } });
    if (url.pathname === '/api/trips') return route.fulfill({ json: [] });
    if (url.pathname === '/api/travel-mode') return route.fulfill({ json: { trip: null, currencies: ['BYN'] } });
    if (url.pathname === '/api/categories') return route.fulfill({ json: [{ name: 'Продукты', subcategories: [] }] });
    if (url.pathname === '/api/home') {
      const month = url.searchParams.get('month') ?? '2026-01';
      const total = month === '2025-12' ? '125' : '50';
      return route.fulfill({ json: { month, total, previous_total: '0', change: total, change_percent: null, categories: [{ category: 'Продукты', amount: total }], recent: [] } });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'январь 2026 г.' })).toBeVisible();
  const overview = page.locator('.overview');
  await overview.dispatchEvent('touchstart', { touches: [{ identifier: 1, clientX: 100, clientY: 350 }] });
  await overview.dispatchEvent('touchend', { touches: [], changedTouches: [{ identifier: 1, clientX: 280, clientY: 355 }] });
  await expect(page.getByRole('heading', { name: 'декабрь 2025 г.' })).toBeVisible();
  await expect(page.locator('.donut-total strong')).toHaveText('125,00');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await overview.dispatchEvent('touchstart', { touches: [{ identifier: 1, clientX: 280, clientY: 350 }] });
  await overview.dispatchEvent('touchend', { touches: [], changedTouches: [{ identifier: 1, clientX: 100, clientY: 355 }] });
  await expect(page.getByRole('heading', { name: 'январь 2026 г.' })).toBeVisible();
  await expect(page.locator('.donut-total strong')).toHaveText('50,00');
  // A click generated at the end of a swipe must not open the expense editor.
  await page.getByRole('button', { name: 'Добавить расход: Продукты' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Следующий месяц' }).click();
  await expect(page.getByRole('heading', { name: 'февраль 2026 г.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('home-months.png'), fullPage: true });
});
