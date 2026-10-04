import { expect, test } from '@playwright/test';

for (const theme of ['light', 'dark'] as const) {
  test(`этап 6: фильтры, страницы, просмотр, правка и удаление · ${theme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.route('https://telegram.org/**', (route) => route.abort());
    let own = { transaction_id: 'own', version: 'a'.repeat(64), date: '2026-10-04', amount: '12.50', category: 'Еда', description: 'Кафе', author_id: 42, author_name: 'Иван', created_at: null, updated_at: null };
    const other = { ...own, transaction_id: 'other', author_id: 43, author_name: 'Анна', description: 'Магазин' };
    let deleted = false; let filtered = false; let edits = 0; let deletions = 0; let reads = 0;
    await page.route('**/api/**', async (route) => {
      const request = route.request(); const url = new URL(request.url());
      expect(request.headers()['x-dev-telegram-user-id']).toBe('42');
      if (url.pathname === '/api/me') return route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } });
      if (url.pathname === '/api/categories') return route.fulfill({ json: [{ name: 'Еда', subcategories: ['Кафе'] }] });
      if (url.pathname === '/api/home') return route.fulfill({ json: { month: '2026-10', total: deleted ? '0' : own.amount, previous_total: '0', change: own.amount, change_percent: null, categories: [], recent: deleted ? [] : [own] } });
      if (url.pathname === '/api/transactions/categories') return route.fulfill({ json: ['Еда'] });
      if (url.pathname === '/api/transactions/participants') return route.fulfill({ json: [{ author_id: 42, author_name: 'Иван' }, { author_id: 43, author_name: 'Анна' }] });
      if (url.pathname === '/api/transactions') {
        reads++;
        if (url.searchParams.get('search')) { filtered = true; expect(url.searchParams.get('search')).toBe('Кафе'); return route.fulfill({ json: { items: [own], total: 1, next_offset: null } }); }
        return route.fulfill({ json: deleted ? { items: [other], total: 1, next_offset: null } : url.searchParams.get('offset') ? { items: [other], total: 2, next_offset: null } : { items: [own], total: 2, next_offset: 1 } });
      }
      if (url.pathname === '/api/transactions/own' && request.method() === 'PATCH') {
        const input = request.postDataJSON(); expect(input.version).toBe(own.version); expect(input.amount).toBe('15.00');
        edits++; own = { ...own, ...input, version: 'b'.repeat(64) }; return route.fulfill({ json: own });
      }
      if (url.pathname === '/api/transactions/own' && request.method() === 'DELETE') {
        expect(url.searchParams.get('version')).toBe(own.version); deleted = true; deletions++; return route.fulfill({ status: 204 });
      }
      return route.fulfill({ status: 404, json: {} });
    });
    await page.goto('/'); await page.getByRole('button', { name: 'Транзакции', exact: true }).click();
    await page.getByRole('button', { name: 'Загрузить ещё' }).click();
    await page.getByRole('button', { name: /Магазин/ }).click();
    await expect(page.getByRole('button', { name: 'Сохранить изменения' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Закрыть операцию' }).click();
    await page.getByRole('button', { name: 'Фильтры' }).click();
    await page.getByLabel('Поиск по описанию').fill('Кафе'); await page.getByRole('button', { name: 'Применить фильтры' }).click();
    await expect(page.getByText('Найдено операций: 1')).toBeVisible(); expect(filtered).toBe(true);
    const beforeRefresh = reads;
    await page.evaluate(() => {
      window.scrollTo(0, 0);
      const target = document.querySelector('[aria-label="Список транзакций"]')!;
      const touch = (y: number) => new Touch({ identifier: 1, target, clientX: 100, clientY: y });
      target.dispatchEvent(new TouchEvent('touchstart', { bubbles: true, touches: [touch(100)] }));
      target.dispatchEvent(new TouchEvent('touchmove', { bubbles: true, cancelable: true, touches: [touch(280)] }));
      target.dispatchEvent(new TouchEvent('touchend', { bubbles: true, touches: [] }));
    });
    await expect.poll(() => reads).toBe(beforeRefresh + 1);
    await expect(page.getByText('Найдено операций: 1')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Обновить список', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: /Фильтры/ }).click();
    await page.getByRole('button', { name: 'Сбросить' }).click();
    await page.getByRole('button', { name: /Кафе/ }).click();
    await expect(page.getByRole('dialog', { name: 'Редактировать расход' })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`transaction-editor-${theme}.png`), fullPage: false });
    await page.getByLabel('Сумма операции, BYN').fill('15,00'); await page.getByRole('button', { name: 'Сохранить изменения' }).click();
    await expect(page.getByText('Операция изменена.')).toBeVisible(); expect(edits).toBe(1);
    await page.getByRole('button', { name: 'Главная', exact: true }).click();
    await expect(page.locator('.donut-total strong')).toHaveText('15,00');
    await page.getByRole('button', { name: 'Транзакции', exact: true }).click();
    await page.getByRole('button', { name: /Кафе/ }).click(); await page.getByRole('button', { name: 'Удалить', exact: true }).click();
    expect(deletions).toBe(0); await page.getByRole('button', { name: 'Отмена удаления' }).click(); expect(deletions).toBe(0);
    await page.getByRole('button', { name: 'Удалить', exact: true }).click(); await page.getByRole('button', { name: 'Подтвердить удаление' }).click();
    await expect(page.getByText('Операция удалена.')).toBeVisible(); expect(deletions).toBe(1);
    await expect(page.getByRole('button', { name: /Кафе/ })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`transactions-${theme}.png`), fullPage: true });
  });
}
