import { expect, test } from '@playwright/test';

for (const query of ['?amount=12%2C50', '?tgWebAppStartParam=expense_12_50']) {
  test(`ссылка iPhone: ${query}`, async ({ page }) => {
    await page.route('https://telegram.org/**', route => route.abort());
    await page.route('**/api/me', route => route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } }));
    await page.route('**/api/trips', route => route.fulfill({ json: [] }));
    await page.route('**/api/travel-mode', route => route.fulfill({ json: { trip: null, currencies: ['BYN', 'EUR'] } }));
    await page.route('**/api/categories', route => route.fulfill({ json: [{ name: 'Еда', subcategories: [] }] }));
    await page.route('**/api/home', route => route.fulfill({ json: { month: '2026-11', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] } }));
    let writes = 0;
    await page.route('**/api/transactions', async route => {
      writes++;
      expect(route.request().method()).toBe('POST');
      expect(route.request().postDataJSON()).toMatchObject({ amount: '12.50', category: 'Еда', currency: 'BYN', trip_id: null });
      await route.fulfill({ status: 201, json: { transaction_id: 'link-test', ...route.request().postDataJSON() } });
    });
    await page.goto(`/${query}`);
    await expect(page.getByRole('dialog', { name: 'Новый расход' })).toBeVisible();
    await expect(page.getByLabel('Сумма, BYN')).toHaveValue('12.50');
    await expect(page.getByRole('button', { name: 'Сохранить расход' })).toBeEnabled();
    expect(writes).toBe(0);
    await page.getByLabel('Категория', { exact: true }).selectOption('Еда');
    await page.getByRole('button', { name: 'Сохранить расход' }).click();
    await expect(page.getByText('Расход сохранён.', { exact: true })).toBeVisible();
    expect(writes).toBe(1);
    await page.getByRole('button', { name: 'Добавить расход: Еда' }).click();
    await expect(page.getByLabel('Сумма, BYN')).toHaveValue('');
  });
}
