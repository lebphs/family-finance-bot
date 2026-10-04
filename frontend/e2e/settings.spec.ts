import { expect, test } from '@playwright/test';

for (const theme of ['light', 'dark'] as const) {
  test(`напоминания: сохранение после перезагрузки и тема ${theme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.route('https://telegram.org/**', route => route.abort());
    await page.route('**/api/me', route => route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } }));
    await page.route('**/api/categories', route => route.fulfill({ json: [] }));
    await page.route('**/api/home', route => route.fulfill({ json: { month: '2026-10', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] } }));
    let settings = { reminder_enabled: false, reminder_time: '22:00', reminder_days: [0,1,2,3,4,5,6], timezone: 'Europe/Minsk', chat_connected: false };
    let saves = 0;
    await page.route('**/api/reminders', async route => {
      if (route.request().method() === 'PUT') {
        saves++;
        expect(route.request().headers()['x-dev-telegram-user-id']).toBe('42');
        expect(route.request().postDataJSON()).not.toHaveProperty('chat_connected');
        settings = { ...settings, ...route.request().postDataJSON() };
      }
      await route.fulfill({ json: settings });
    });
    await page.goto('/');
    await page.getByRole('button', { name: 'Настройки', exact: true }).click();
    await expect(page.getByLabel('Время')).toHaveValue('22:00');
    await page.getByLabel('Включить напоминания').check();
    await page.getByLabel('Время').fill('09:30');
    await page.getByLabel('Вс', { exact: true }).uncheck();
    await page.getByRole('button', { name: 'Сохранить настройки' }).click();
    await expect(page.getByText('Настройки сохранены')).toBeVisible();
    expect(saves).toBe(1);
    await page.reload();
    await page.getByRole('button', { name: 'Настройки', exact: true }).click();
    await expect(page.getByLabel('Время')).toHaveValue('09:30');
    await expect(page.getByLabel('Включить напоминания')).toBeChecked();
    await expect(page.getByLabel('Вс', { exact: true })).not.toBeChecked();
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`settings-${theme}.png`), fullPage: true });
  });
}
