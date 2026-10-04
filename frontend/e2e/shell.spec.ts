import { expect, test } from '@playwright/test';
import { emptyStatistics } from '../src/test/statistics';
import { createServer } from 'node:http';

// All external boundaries are intercepted. No bot, spreadsheet or Telegram request.
test.beforeEach(async ({ page }) => {
  await page.route('https://telegram.org/**', (route) => route.abort());
  await page.route('**/api/transactions?*', (route) => route.fulfill({ json: { items: [], total: 0, next_offset: null } }));
  await page.route('**/api/transactions/participants', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/transactions/categories', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/reminders', route => route.fulfill({ json: { reminder_enabled: false, reminder_time: '22:00', reminder_days: [0,1,2,3,4,5,6], timezone: 'Europe/Minsk', chat_connected: false } }));
  await page.route('**/api/categories', (route) => route.fulfill({ json: [{ name: 'Еда', subcategories: ['Кафе'] }] }));
  await page.route('**/api/statistics?*', (route) => route.fulfill({ json: emptyStatistics }));
  await page.route('**/api/home', (route) => route.fulfill({ json: { month: '2026-10', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] } }));
});

for (const theme of ['light', 'dark'] as const) {
  test(`браузер без Telegram: навигация и тема ${theme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    await page.route('**/api/me', async (route) => {
      expect(route.request().headers()['x-dev-telegram-user-id']).toBe('42');
      await route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } });
    });
    await page.goto('/');
    await expect(page.getByRole('navigation')).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    for (const name of ['Транзакции', 'Статистика', 'Настройки', 'Главная']) {
      await page.getByRole('button', { name, exact: true }).click();
      await expect(page.getByRole('button', { name, exact: true })).toHaveAttribute('aria-current', 'page');
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`mobile-${theme}.png`), fullPage: true });
  });
}

test('неизвестный пользователь видит только отказ', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ status: 403, json: { error: { code: 'access_denied', message: 'Нет доступа' } } }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Нет доступа' })).toBeVisible();
  await expect(page.getByRole('navigation')).toHaveCount(0);
});

test('SDK: initData, смена темы и безопасные отступы', async ({ page }) => {
  await page.addInitScript(() => {
    const callbacks: Record<string, () => void> = {};
    const app = {
      initData: 'test-signed-data', colorScheme: 'dark', themeParams: { bg_color: '#101010' },
      safeAreaInset: { top: 24, bottom: 20, left: 0, right: 0 },
      contentSafeAreaInset: { top: 8, bottom: 4, left: 0, right: 0 },
      ready() {}, expand() {},
      onEvent(event: string, callback: () => void) { callbacks[event] = callback; }, offEvent() {},
    };
    Object.assign(window, { Telegram: { WebApp: app }, testThemeChange: () => { app.colorScheme = 'light'; callbacks.themeChanged(); } });
  });
  await page.route('**/api/me', async (route) => {
    expect(route.request().headers().authorization).toBe('tma test-signed-data');
    expect(route.request().headers()['x-dev-telegram-user-id']).toBeUndefined();
    await route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'admin' } });
  });
  await page.goto('/');
  await expect(page.getByRole('navigation')).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.locator('nav').evaluate((nav) => getComputedStyle(nav).paddingBottom)).toBe('32px');
  await page.evaluate(() => (window as unknown as { testThemeChange(): void }).testThemeChange());
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('ошибка сервера и повторная загрузка', async ({ page }) => {
  let unavailable = true;
  await page.route('**/api/me', (route) => unavailable
    ? route.fulfill({ status: 503, json: { error: { code: 'storage_unavailable' } } })
    : route.fulfill({ json: { telegram_user_id: 42, display_name: 'Иван', role: 'member' } }));
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Повторить' })).toBeVisible();
  unavailable = false;
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(page.getByRole('navigation')).toBeVisible();
});

test('Vite проксирует API и удаляет dev-заголовок для хоста туннеля', async ({ request }) => {
  const server = createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ path: req.url, dev: req.headers['x-dev-telegram-user-id'] ?? null, auth: req.headers.authorization ?? null }));
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(18000, '127.0.0.1', resolve);
  });
  try {
    const local = await request.get('/api/me', { headers: { 'X-Dev-Telegram-User-Id': '42' } });
    expect(await local.json()).toMatchObject({ path: '/api/me', dev: '42' });
    const tunnel = await request.get('/api/me', { headers: {
      Host: 'stage4-test.trycloudflare.com', 'X-Dev-Telegram-User-Id': '42', Authorization: 'tma test-signed-data',
    } });
    expect(await tunnel.json()).toMatchObject({ dev: null, auth: 'tma test-signed-data' });
    const deniedHost = await request.get('/', { headers: { Host: 'unknown.example' } });
    expect(deniedHost.status()).toBe(403);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});
