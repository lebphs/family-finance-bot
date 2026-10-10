import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, AuthContext, authHeaders } from './api';

const auth: AuthContext = {
  initData: '', development: true, devAuthEnabled: true, devUserId: '42', hostname: 'localhost',
};

describe('авторизация API', () => {
  it('отправляет расход с авторизацией и ключом, не добавляя автора в тело', async () => {
    const send = vi.fn().mockResolvedValue(new Response('{}', { status: 201 }));
    const client = new ApiClient(() => ({ ...auth, initData: 'signed=data' }), send);
    const input = { request_id: 'test-key', date: '2026-10-03', amount: '12.50', category: 'Еда', description: '' };
    await client.createExpense(input);
    expect(send.mock.calls[0][0]).toBe('/api/transactions');
    expect(send.mock.calls[0][1]).toMatchObject({ method: 'POST', headers: { Authorization: 'tma signed=data', 'Content-Type': 'application/json' } });
    expect(JSON.parse(send.mock.calls[0][1].body)).toEqual(input);
  });

  it('передаёт исходный initData в каждом запросе и предпочитает Telegram dev-режиму', async () => {
    let initData = 'signed=first&hash=abc';
    const send = vi.fn().mockImplementation(async () => new Response('{}'));
    const client = new ApiClient(() => ({ ...auth, initData }), send);
    await client.me();
    initData = 'signed=second&hash=def';
    await client.categories();
    expect(send.mock.calls.map(([url, options]) => [url, options.headers])).toEqual([
      ['/api/me', { Authorization: 'tma signed=first&hash=abc' }],
      ['/api/categories', { Authorization: 'tma signed=second&hash=def' }],
    ]);
    expect(send.mock.calls[0][1]).toMatchObject({ credentials: 'omit', redirect: 'error', cache: 'no-store' });
  });

  it('разрешает dev-заголовок только при явной настройке на localhost', () => {
    expect(authHeaders(auth)).toEqual({ 'X-Dev-Telegram-User-Id': '42' });
    expect(authHeaders({ ...auth, hostname: '127.0.0.1' })).toEqual({ 'X-Dev-Telegram-User-Id': '42' });
  });

  it.each([
    { development: false }, { devAuthEnabled: false }, { hostname: 'example.trycloudflare.com' },
    { devUserId: '' }, { devUserId: '-1' }, { devUserId: '1e2' }, { devUserId: '9007199254740992' },
  ])('отклоняет небезопасную dev-авторизацию: %j', (change) => {
    expect(() => authHeaders({ ...auth, ...change })).toThrow(ApiError);
  });

  it('без авторизации вообще не обращается к API', async () => {
    const send = vi.fn();
    const client = new ApiClient(() => ({ ...auth, devAuthEnabled: false }), send);
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
    expect(send).not.toHaveBeenCalled();
  });

  it.each([401, 403])('сохраняет отказ %i и не раскрывает тело ответа', async (status) => {
    const client = new ApiClient(() => auth, vi.fn().mockResolvedValue(new Response('secret', { status })));
    await expect(client.me()).rejects.toMatchObject({ status, accessDenied: true, message: 'Нет доступа' });
  });

  it('обрабатывает недоступный backend и ошибку Google API', async () => {
    const offline = new ApiClient(() => auth, vi.fn().mockRejectedValue(new TypeError('internal URL')));
    await expect(offline.me()).rejects.toMatchObject({ status: 0, code: 'network_error' });
    const unavailable = new ApiClient(() => auth, vi.fn().mockResolvedValue(new Response('credentials', { status: 503 })));
    await expect(unavailable.me()).rejects.toMatchObject({ status: 503, code: 'request_failed' });
  });

  it('обрабатывает ответ не в JSON', async () => {
    const client = new ApiClient(() => auth, vi.fn().mockResolvedValue(new Response('<html>')));
    await expect(client.me()).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('передаёт AbortSignal и сохраняет отмену запроса', async () => {
    const controller = new AbortController();
    controller.abort();
    const error = new DOMException('Aborted', 'AbortError');
    const send = vi.fn().mockRejectedValue(error);
    const client = new ApiClient(() => auth, send);
    await expect(client.me(controller.signal)).rejects.toBe(error);
    expect(send.mock.calls[0][1].signal).toBe(controller.signal);
  });
});

it('передаёт фильтры, PATCH по версии и DELETE с пустым ответом', async () => {
  const send = vi.fn().mockResolvedValueOnce(new Response('{"items":[],"total":0,"next_offset":null}'))
    .mockResolvedValueOnce(new Response('{}')).mockResolvedValueOnce(new Response(null, { status: 204 }));
  const client = new ApiClient(() => ({ ...auth, initData: 'verified' }), send);
  await client.transactions({ search: 'Кафе & магазин', offset: '20' });
  const url = new URL(send.mock.calls[0][0], 'http://test'); expect(url.searchParams.get('search')).toBe('Кафе & магазин'); expect(url.searchParams.get('offset')).toBe('20');
  const input = { date: '2026-10-04', amount: '1', category: 'Еда', description: '', version: 'a'.repeat(64) };
  await client.updateTransaction('id/encoded', input); expect(send.mock.calls[1][0]).toBe('/api/transactions/id%2Fencoded');
  expect(send.mock.calls[1][1].method).toBe('PATCH'); expect(JSON.parse(send.mock.calls[1][1].body)).toEqual(input);
  await expect(client.deleteTransaction('id', input.version)).resolves.toBeUndefined(); expect(send.mock.calls[2][1].method).toBe('DELETE');
  expect(send.mock.calls.every((call) => call[1].headers.Authorization === 'tma verified')).toBe(true);
});

it('статистика: отправляет параметры и проверенную авторизацию в GET с AbortSignal', async () => {
  const send = vi.fn().mockResolvedValue(new Response('{}'));
  const client = new ApiClient(() => ({ ...auth, initData: 'verified' }), send);
  const controller = new AbortController();
  await client.statistics({ mode: 'compare', compare_from: '2026-01', compare_to: '2026-03', unknown_author: 'true' }, controller.signal);
  const [path, options] = send.mock.calls[0];
  const url = new URL(path, 'http://test');
  expect(url.pathname).toBe('/api/statistics');
  expect(Object.fromEntries(url.searchParams)).toEqual({ mode: 'compare', compare_from: '2026-01', compare_to: '2026-03', unknown_author: 'true' });
  expect(options).toMatchObject({ method: 'GET', signal: controller.signal, headers: { Authorization: 'tma verified' } });
});
