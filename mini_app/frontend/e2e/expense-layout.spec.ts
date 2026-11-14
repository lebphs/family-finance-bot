import { expect, test } from '@playwright/test';

test('форма расхода целиком помещается в мобильном окне Telegram', async ({ page }) => {
  await page.route('https://telegram.org/**', route => route.abort());
  await page.route('**/api/me', route => route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } }));
  await page.route('**/api/categories', route => route.fulfill({ json: [{ name: 'Здоровье', subcategories: ['Аптека'] }] }));
  await page.route('**/api/trips', route => route.fulfill({ json: [] }));
  await page.route('**/api/travel-mode', route => route.fulfill({ json: { trip: null, currencies: ['BYN', 'EUR', 'USD'] } }));
  await page.route('**/api/home', route => route.fulfill({ json: { month: '2026-11', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Добавить расход: Здоровье' }).click();

  for (const [width, height] of [[390, 700], [390, 600], [320, 568]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(height => {
      const root = document.documentElement;
      root.style.setProperty('--app-height', `${height}px`);
      root.style.setProperty('--tg-safe-bottom', '20px');
      root.style.setProperty('--tg-content-safe-top', '12px');
    }, height);
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(page.getByRole('button', { name: 'Отменить' })).toBeFocused();
    await expect(page.getByLabel('Сумма, BYN')).toHaveAttribute('inputmode', 'decimal');
    await expect(page.getByRole('button', { name: '1', exact: true })).toHaveCount(0);
    expect(await dialog.evaluate(element => element.scrollHeight - element.clientHeight), `${width}×${height}: no vertical scroll`).toBeLessThanOrEqual(1);
    for (const control of [page.getByLabel('Дата', { exact: true }), page.getByLabel('Сумма, BYN'), page.getByLabel('Подкатегория', { exact: true }), page.getByRole('button', { name: 'Сохранить расход', exact: true })]) {
      await expect(control).toBeInViewport({ ratio: 1 });
    }
    await page.screenshot({ path: test.info().outputPath(`expense-${width}-${height}.png`) });
  }
});
