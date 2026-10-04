import { expect, test } from '@playwright/test';
import { statisticsFixture } from '../src/test/statistics';

test.use({ locale: 'ru-RU' });

for (const theme of ['light', 'dark'] as const) {
  test(`этап 7: месяцы, участники и сравнение · ${theme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.route('https://telegram.org/**', (route) => route.abort());
    let requests = 0;
    await page.route('**/api/**', async (route) => {
      const request = route.request(); const url = new URL(request.url());
      expect(request.headers()['x-dev-telegram-user-id']).toBe('42');
      if (url.pathname === '/api/me') return route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } });
      if (url.pathname === '/api/categories') return route.fulfill({ json: [] });
      if (url.pathname === '/api/home') return route.fulfill({ json: { month: '2026-10', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] } });
      if (url.pathname === '/api/statistics') {
        requests++;
        const query = url.searchParams;
        if (query.get('mode') === 'range') {
          expect(query.get('month_from')).toBe('2026-01'); expect(query.get('month_to')).toBe('2026-03');
        }
        const unknown = query.get('unknown_author') === 'true';
        const author = query.get('author_id');
        const compare = query.get('mode') === 'compare';
        if (compare) { expect(query.get('compare_from')).toBe('2026-02'); expect(query.get('compare_to')).toBe('2026-03'); }
        const base = compare ? {
          ...statisticsFixture, months: ['2026-02', '2026-03'], total: '120', family_total: '120', count: 2,
          categories: [{ category: 'Транспорт', amount: '90' }, { category: 'Еда', amount: '30' }],
          monthly: statisticsFixture.monthly.slice(1).map((m, i) => i === 0 ? { ...m, change: null, change_percent: null } : m),
          participants: statisticsFixture.participants.map((p) => ({ ...p,
            total: p.author_id === 42 ? '30' : p.author_id === 43 ? '90' : '0',
            count: p.author_id === null ? 0 : 1, average: p.author_id === 42 ? '30' : p.author_id === 43 ? '90' : '0',
            share_percent: p.author_id === 42 ? '25' : p.author_id === 43 ? '75' : '0',
            categories: p.author_id === null ? [] : [{ category: p.author_id === 42 ? 'Еда' : 'Транспорт', amount: p.author_id === 42 ? '30' : '90' }],
            monthly: p.monthly.slice(1).map((m, i) => i === 0 ? { ...m, change: null, change_percent: null } : m),
          })),
        } : statisticsFixture;
        return route.fulfill({ json: { ...base,
          author_id: author ? Number(author) : null, unknown_author: unknown,
          total: unknown ? '10' : author ? '60' : base.total, count: unknown ? 1 : author ? 3 : base.count,
          comparison: compare ? { month_from: '2026-02', month_to: '2026-03', from_total: '0', to_total: '120', change: '120', change_percent: null } : null,
        } });
      }
      return route.fulfill({ status: 404, json: {} });
    });
    await page.goto('/'); await page.getByRole('button', { name: 'Статистика', exact: true }).click();
    await expect(page.getByRole('img', { name: 'Столбчатый график расходов по месяцам и участникам' })).toBeVisible();
    const initialRequests = requests;
    await expect(page.getByRole('region', { name: 'Период и участник' })).toBeHidden();
    await page.getByRole('button', { name: 'Фильтры' }).click();
    await page.getByLabel('Период статистики').selectOption('range');
    await page.getByLabel('Начальный месяц').fill('2026-01'); await page.getByLabel('Конечный месяц').fill('2026-03');
    await page.getByRole('button', { name: 'Показать статистику' }).click();
    await page.getByText('Суммы по месяцам', { exact: true }).click();
    await expect(page.getByRole('table')).toContainText('-100 %');
    await expect(page.getByRole('columnheader', { name: 'Изменение, %' })).toBeVisible();
    await page.getByText(/Иван · 60,00 BYN · доля/).click();
    await expect(page.getByText('Средняя сумма: 20,00 BYN')).toBeVisible();
    await expect(page.getByRole('list', { name: 'Динамика: Иван', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Фильтры' }).click();
    await page.getByLabel('Участник статистики').selectOption('42'); await page.getByRole('button', { name: 'Показать статистику' }).click();
    await page.getByRole('button', { name: 'Фильтры' }).click();
    await page.getByLabel('Участник статистики').selectOption('unknown'); await page.getByRole('button', { name: 'Показать статистику' }).click();
    await page.getByRole('button', { name: 'Фильтры' }).click();
    await page.getByLabel('Участник статистики').selectOption('');
    await page.getByLabel('Период статистики').selectOption('compare');
    await page.getByLabel('Базовый месяц').fill('2026-02'); await page.getByLabel('Сравниваемый месяц').fill('2026-03');
    await page.getByRole('button', { name: 'Показать статистику' }).click();
    await expect(page.getByText('Разница: 120,00 BYN')).toBeVisible();
    await expect(page.getByText('Изменение: не определён')).toBeVisible();
    await expect.poll(() => requests - initialRequests).toBe(4);
    const monthlyTable = page.getByRole('table');
    if (!await monthlyTable.isVisible()) await page.getByText('Суммы по месяцам', { exact: true }).click();
    await expect(monthlyTable).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`statistics-${theme}.png`), fullPage: true });
  });
}
