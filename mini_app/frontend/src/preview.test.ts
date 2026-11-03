import { describe, expect, it, vi } from 'vitest';
import { createPreviewClient } from './preview';
import { localPreviewEnabled } from './preview-mode';

describe('локальный просмотр UI', () => {
  it('доступен только при явном включении на loopback в development без Telegram', () => {
    expect(localPreviewEnabled(true, 'true', 'localhost', '')).toBe(true);
    expect(localPreviewEnabled(true, 'true', '127.0.0.1', '')).toBe(true);
    expect(localPreviewEnabled(false, 'true', 'localhost', '')).toBe(false);
    expect(localPreviewEnabled(true, undefined, 'localhost', '')).toBe(false);
    expect(localPreviewEnabled(true, 'false', 'localhost', '')).toBe(false);
    expect(localPreviewEnabled(true, 'true', 'example.trycloudflare.com', '')).toBe(false);
    expect(localPreviewEnabled(true, 'true', 'localhost', 'signed')).toBe(false);
  });

  it('загружает все разделы, меняет только демоданные и сбрасывает их при новом запуске', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Unexpected network'));
    const client = createPreviewClient();
    expect((await client.me()).display_name).toBe('Иван');
    expect((await client.categories()).length).toBeGreaterThan(0);
    const before = await client.home();
    const input = { request_id: 'demo-request', date: `${before.month}-02`, category: 'Продукты', amount: '15.00', description: 'Тестовая покупка' };
    const saved = await client.createExpense(input);
    expect((await client.createExpense(input)).transaction_id).toBe(saved.transaction_id);
    expect(Number((await client.home()).total)).toBeCloseTo(Number(before.total) + 15);
    expect((await client.transactions({ search: 'Тестовая покупка' })).total).toBe(1);
    const edited = await client.updateTransaction(saved.transaction_id!, { ...input, amount: '20.00', version: saved.version! });
    expect(edited.version).not.toBe(saved.version);
    await expect(client.deleteTransaction(edited.transaction_id!, saved.version!)).rejects.toMatchObject({ status: 409 });
    await client.deleteTransaction(edited.transaction_id!, edited.version!);
    expect((await client.home()).total).toBe(before.total);
    expect((await client.statistics()).total).toBe(before.total);
    expect((await client.statistics({ mode: 'months', months: '3' })).months).toHaveLength(3);
    expect((await client.statistics({ mode: 'compare', compare_from: before.month, compare_to: before.month })).comparison?.change).toBe('0.00');
    expect((await client.participants()).length).toBe(2);
    const settings = await client.reminders();
    expect((await client.saveReminders({ ...settings, reminder_time: '21:00' })).reminder_time).toBe('21:00');
    expect((await createPreviewClient().reminders()).reminder_time).toBe('20:00');
    expect(fetch).not.toHaveBeenCalled();
  });
});

it('демостатистика содержит 12 предыдущих месяцев с расходами обоих участников', async () => {
  const data = await createPreviewClient().statistics({ mode: 'months', months: '12' });
  expect(data.monthly).toHaveLength(12);
  expect(data.monthly.every(month => Number(month.total) > 0)).toBe(true);
  expect(new Set(data.monthly.map(month => month.total)).size).toBeGreaterThan(3);
  expect(data.participants).toHaveLength(2);
  for (const person of data.participants) expect(person.monthly.every(month => Number(month.total) > 0)).toBe(true);
});

it('предпросмотр поездок использует только демонстрационные курсы и учитывает предоплаты', async () => {
  const client = createPreviewClient();
  const trip = await client.createTrip({ name: 'Италия', date_from: '2026-03-10', date_to: '2026-03-20', currency: 'EUR' });
  expect((await client.travelContext()).trip).toBeNull();
  await client.createExpense({ request_id: 'flight', date: '2026-01-10', amount: '100', currency: 'EUR', trip_id: trip.trip_id, category: 'Междугородний транспорт', description: 'Билеты' });
  const report = await client.tripReport(trip.trip_id);
  expect(report.total).toBe('350.00');
  expect(report.transactions[0].rate_source).toBe('DEMO');
  await client.setTravelMode(trip.trip_id);
  expect((await client.travelContext()).trip?.trip_id).toBe(trip.trip_id);
  await client.completeTrip(trip.trip_id);
  expect((await client.travelContext()).trip).toBeNull();
  expect((await client.tripReport(trip.trip_id)).total).toBe('350.00');
});

it('расход поездки виден в её отчёте и истории, но не меняет основную статистику', async () => {
  const client = createPreviewClient();
  const beforeHome = await client.home();
  const beforeStatistics = await client.statistics({ months: '6' });
  const trip = await client.createTrip({ name: 'Отпуск', date_from: `${beforeHome.month}-01`, date_to: `${beforeHome.month}-20`, currency: 'EUR' });
  const expense = await client.createExpense({ request_id: 'travel-only', date: `${beforeHome.month}-02`, amount: '1000', currency: 'EUR', trip_id: trip.trip_id, category: 'Проживание', description: 'Отель' });
  expect(await client.home()).toEqual(beforeHome);
  expect(await client.statistics({ months: '6' })).toEqual(beforeStatistics);
  expect((await client.tripReport(trip.trip_id)).total).toBe('3500.00');
  expect((await client.transactions({ trip_id: trip.trip_id })).items[0].transaction_id).toBe(expense.transaction_id);
});
