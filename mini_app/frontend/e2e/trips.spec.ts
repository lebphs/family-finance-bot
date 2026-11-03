import { expect, test } from '@playwright/test';

test('поездка: отчёт, предоплата и автоматическая валюта на мобильном экране', async ({ page }) => {
  const trip = { trip_id: 'italy', name: 'Италия', date_from: '2026-03-10', date_to: '2026-03-20', currency: 'EUR', created_by: 42, completed: false };
  const categories = [{ name: 'Проживание', subcategories: [] }, { name: 'Междугородний транспорт', subcategories: [] }];
  let active = false;
  let saved = false;
  await page.route('https://telegram.org/**', route => route.abort());
  await page.route('**/api/me', route => route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } }));
  await page.route('**/api/trips', route => route.fulfill({ json: [trip] }));
  await page.route('**/api/travel-mode', route => {
    if (route.request().method() === 'PUT') active = !!route.request().postDataJSON().trip_id;
    return route.fulfill({ json: { trip: active ? trip : null, currencies: ['BYN', 'EUR', 'PLN'] } });
  });
  await page.route('**/api/categories*', route => route.fulfill({ json: route.request().url().includes('travel=true') ? categories : [{ name: 'Продукты', subcategories: [] }] }));
  await page.route('**/api/home', route => route.fulfill({ json: { month: '2026-03', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] } }));
  await page.route('**/api/trips/italy/report', route => route.fulfill({ json: {
    trip, total: '350.00', count: 1, categories: [{ category: 'Междугородний транспорт', amount: '350.00' }], participants: [{ author_id: 42, author_name: 'Иван', amount: '350.00' }],
    transactions: [{ transaction_id: 'flight', date: '2026-01-10', category: 'Междугородний транспорт', description: 'Билеты заранее', amount: '350.00', original_amount: '100.00', currency: 'EUR', author_id: 42, author_name: 'Иван', created_at: null, updated_at: null }],
  } }));
  await page.route('**/api/transactions', route => {
    const payload = route.request().postDataJSON();
    expect(payload).toMatchObject({ trip_id: 'italy', currency: 'EUR', amount: '25', category: 'Проживание', date: '2026-01-15' });
    saved = true;
    return route.fulfill({ status: 201, json: { ...payload, transaction_id: 'hotel', amount: '87.50', original_amount: '25' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Поездки', exact: true }).click();
  await page.getByRole('button', { name: /Италия/ }).click();
  const report = page.getByRole('region', { name: 'Отчёт поездки' });
  await expect(report).toContainText('100.00 EUR');
  await expect(report).toContainText('2026-01-10');
  await page.screenshot({ path: test.info().outputPath('travel-report-mobile.png'), fullPage: true });
  await report.getByRole('button', { name: 'Добавить расход в эту поездку' }).click();
  await expect(page.getByLabel('Поездка расхода')).toHaveValue('italy');
  await expect(page.getByLabel('Валюта расхода')).toHaveValue('EUR');
  await page.getByLabel('Сумма, EUR').fill('25');
  await page.getByLabel('Категория', { exact: true }).selectOption('Проживание');
  await page.getByLabel('Дата', { exact: true }).fill('2026-01-15');
  await page.screenshot({ path: test.info().outputPath('travel-expense-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: 'Сохранить расход', exact: true }).click();
  await expect(page.getByText('Расход сохранён.')).toBeVisible();
  expect(saved).toBe(true);
  expect(active).toBe(false);
  await page.getByRole('button', { name: 'Поездки', exact: true }).click();
  await page.getByRole('button', { name: /Италия/ }).click();
  await page.getByRole('button', { name: 'Включить режим этой поездки' }).click();
  await expect(page.getByText(/Ваш активный режим/)).toBeVisible();
  await page.getByRole('button', { name: 'Главная', exact: true }).click();
  await expect(page.getByLabel('Расходы для')).toHaveValue('italy');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('travel-mode-mobile.png'), fullPage: true });
});
