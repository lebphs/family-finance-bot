import { expect, test } from '@playwright/test';

for (const theme of ['light', 'dark'] as const) {
  test(`главная: мобильное сохранение и обновление, ${theme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.route('https://telegram.org/**', (route) => route.abort());
    await page.route('**/api/transactions?*', (route) => route.fulfill({ json: { items: [], total: 0, next_offset: null } }));
    await page.route('**/api/transactions/participants', (route) => route.fulfill({ json: [] }));
    await page.route('**/api/transactions/categories', (route) => route.fulfill({ json: [] }));
    await page.route('**/api/me', (route) => route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } }));
    await page.route('**/api/categories', (route) => route.fulfill({ json: [{ name: 'Еда', subcategories: ['Кафе', 'Магазин'] }] }));
    let saved = false; let calls = 0;
    const transaction = { transaction_id: 'saved', date: '2026-10-03', amount: '12.50', category: 'Еда', description: 'Кафе', author_name: 'Иван', author_id: 42, created_at: null, updated_at: null };
    await page.route('**/api/home', (route) => route.fulfill({ json: {
      month: '2026-10', total: saved ? '12.50' : '0', previous_total: '10', change: saved ? '2.50' : '-10', change_percent: saved ? '25' : '-100',
      categories: saved ? [{ category: 'Еда', amount: '12.50' }] : [], recent: saved ? [transaction] : [],
    } }));
    await page.route('**/api/transactions', async (route) => {
      calls++;
      expect(route.request().method()).toBe('POST');
      expect(route.request().headers()['x-dev-telegram-user-id']).toBe('42');
      expect(route.request().postDataJSON()).toMatchObject({ amount: '12.50', category: 'Еда', description: 'Кафе', date: '2026-10-03' });
      expect(route.request().postDataJSON()).not.toHaveProperty('author_id');
      saved = true;
      await route.fulfill({ status: 201, json: transaction });
    });
    await page.goto('/');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: 'Добавить расход: Еда' }).click();
    await expect(page.getByLabel('Категория', { exact: true })).toHaveValue('Еда');
    await expect(page.getByRole('button', { name: 'Сохранить расход' })).toBeEnabled();
    await page.getByLabel('Сумма, BYN').fill('12,50');
    await page.getByLabel('Категория', { exact: true }).selectOption('Еда');
    await page.getByLabel('Подкатегория', { exact: true }).selectOption('Кафе');
    await page.getByLabel('Дата', { exact: true }).fill('2026-10-03');
    await page.screenshot({ path: test.info().outputPath(`expense-${theme}.png`), fullPage: false });
    await page.getByRole('button', { name: 'Отменить' }).click();
    await page.getByRole('button', { name: 'Транзакции', exact: true }).click();
    await page.getByRole('button', { name: 'Главная', exact: true }).click();
    await page.getByRole('button', { name: 'Добавить расход: Еда' }).click();
    await expect(page.getByLabel('Сумма, BYN')).toHaveValue('12,50');
    await page.getByRole('button', { name: 'Сохранить расход' }).click();
    await expect(page.getByText('Расход сохранён.', { exact: true })).toBeVisible();
    await expect(page.locator('.donut-total strong')).toHaveText('12,50');
    await expect(page.getByRole('heading', { name: 'Расходы за текущий месяц' })).toHaveCount(0);
    expect(calls).toBe(1);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`home-${theme}.png`), fullPage: true });
  });
}

test('иконки всех категорий: выбор, клавиатура, отмена и узкий экран', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  const names = ['Продукты', 'Дом', 'Авто', 'Транспорт', 'Кафе', 'Спорт', 'Здоровье', 'Одежда', 'Связь', 'Подарки', 'Питомцы', 'Другое', 'Образование'];
  await page.route('https://telegram.org/**', (route) => route.abort());
  await page.route('**/api/me', (route) => route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } }));
  await page.route('**/api/categories', (route) => route.fulfill({ json: names.map(name => ({ name, subcategories: [] })) }));
  await page.route('**/api/home', (route) => route.fulfill({ json: { month: '2026-10', total: '1000', previous_total: '900', change: '100', change_percent: '11.11', categories: names.slice(0, 5).map(category => ({ category, amount: '200' })), recent: [] } }));
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Добавить расход: Продукты' })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('category-wheel.png'), fullPage: true });
  await page.getByRole('button', { name: 'Добавить расход: Продукты' }).click();
  await expect(page.getByLabel('Категория', { exact: true })).toHaveValue('Продукты');
  for (const name of ['1', '2', 'Десятичная запятая', '5', '0']) await page.getByRole('button', { name, exact: true }).click();
  await expect(page.getByLabel('Сумма, BYN')).toHaveValue('12,50');
  await page.getByRole('button', { name: 'Удалить последнюю цифру' }).click();
  await expect(page.getByLabel('Сумма, BYN')).toHaveValue('12,5');
  await page.screenshot({ path: test.info().outputPath('category-expense.png') });
  await page.getByRole('button', { name: 'Сохранить расход' }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Отменить' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Образование', exact: true }).click();
  await expect(page.getByLabel('Категория', { exact: true })).toHaveValue('Образование');
  await page.getByRole('button', { name: 'Отменить' }).click();
  await page.setViewportSize({ width: 320, height: 740 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
