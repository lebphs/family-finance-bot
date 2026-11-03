import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient, Trip, TripReport } from '../api';
import { Trips } from './Trips';
import { Home } from './Home';
import { Transactions } from './Transactions';

const user = { telegram_user_id: 42, display_name: 'Иван', role: 'member' as const };
const trip: Trip = { trip_id: 'italy', name: 'Италия', date_from: '2026-03-10', date_to: '2026-03-20', currency: 'EUR', created_by: 42, completed: false };
const report: TripReport = { trip, total: '350.00', count: 1, categories: [{ category: 'Междугородний транспорт', amount: '350.00' }], participants: [{ author_id: 42, author_name: 'Иван', amount: '350.00' }], transactions: [{ transaction_id: 'flight', date: '2026-01-10', category: 'Междугородний транспорт', amount: '350.00', original_amount: '100', currency: 'EUR', description: 'Билеты', author_id: 42, author_name: 'Иван', created_at: null, updated_at: null }] };
function setup() {
  const client = new ApiClient();
  vi.spyOn(client, 'trips').mockResolvedValue([trip]);
  vi.spyOn(client, 'travelContext').mockResolvedValue({ trip: null, currencies: ['BYN', 'EUR', 'PLN'] });
  vi.spyOn(client, 'tripReport').mockResolvedValue(report);
  vi.spyOn(client, 'setTravelMode').mockResolvedValue({ trip, currencies: ['BYN', 'EUR', 'PLN'] });
  vi.spyOn(client, 'completeTrip').mockResolvedValue({ ...trip, completed: true });
  const onExpense = vi.fn(); const onChanged = vi.fn();
  render(<Trips client={client} user={user} onDenied={vi.fn()} onExpense={onExpense} onChanged={onChanged} />);
  return { client, onExpense, onChanged };
}

describe('поездки', () => {
  it('показывает предварительные покупки, категории, участников и исходную валюту', async () => {
    setup();
    fireEvent.click(await screen.findByRole('button', { name: /Италия/ }));
    const section = await screen.findByRole('region', { name: 'Отчёт поездки' });
    expect(section).toHaveTextContent('350,00 BYN');
    expect(section).toHaveTextContent('2026-01-10');
    expect(section).toHaveTextContent('100 EUR');
    fireEvent.click(within(section).getByRole('button', { name: /Междугородний транспорт/ }));
    expect(within(section).getByRole('button', { name: 'Показать все расходы поездки' })).toBeInTheDocument();
  });
  it('включает персональный режим и открывает добавление без переключения режима', async () => {
    const { client, onExpense, onChanged } = setup();
    fireEvent.click(await screen.findByRole('button', { name: /Италия/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'Добавить расход в эту поездку' }));
    expect(onExpense).toHaveBeenCalledWith(trip);
    expect(client.setTravelMode).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Включить режим этой поездки' }));
    await waitFor(() => expect(client.setTravelMode).toHaveBeenCalledWith('italy'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });
  it('создаёт поездку с валютой и датами', async () => {
    const { client } = setup();
    vi.spyOn(client, 'createTrip').mockResolvedValue(trip);
    fireEvent.click(await screen.findByRole('button', { name: 'Создать поездку' }));
    fireEvent.change(screen.getByLabelText('Название поездки'), { target: { value: 'Италия' } });
    fireEvent.change(screen.getByLabelText('Начало поездки'), { target: { value: trip.date_from } });
    fireEvent.change(screen.getByLabelText('Окончание поездки'), { target: { value: trip.date_to } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить поездку' }));
    await waitFor(() => expect(client.createTrip).toHaveBeenCalledWith({ name: trip.name, date_from: trip.date_from, date_to: trip.date_to, currency: 'EUR' }));
    expect(await screen.findByRole('region', { name: 'Отчёт поездки' })).toBeInTheDocument();
  });
  it('главная использует валюту и категории режима, обычный расход переключается явно', async () => {
    const client = new ApiClient();
    vi.spyOn(client, 'trips').mockResolvedValue([trip]);
    vi.spyOn(client, 'travelContext').mockResolvedValue({ trip, currencies: ['BYN', 'EUR', 'PLN'] });
    vi.spyOn(client, 'home').mockResolvedValue({ month: '2026-03', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] });
    vi.spyOn(client, 'categories').mockImplementation(async (_, travel) => [{ name: travel ? 'Проживание' : 'Продукты', subcategories: [] }]);
    vi.spyOn(client, 'createExpense').mockResolvedValue(report.transactions[0]);
    render(<Home client={client} onDenied={vi.fn()} onTransactions={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Добавить расход: Проживание' }));
    expect(screen.getByLabelText('Сумма, EUR')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Сумма, EUR'), { target: { value: '25' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    await waitFor(() => expect(client.createExpense).toHaveBeenCalledWith(expect.objectContaining({ trip_id: 'italy', currency: 'EUR', amount: '25' })));
    await screen.findByText('Расход сохранён.');
    fireEvent.change(screen.getByLabelText('Расходы для'), { target: { value: '' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Добавить расход: Продукты' }));
    expect(screen.getByLabelText('Сумма, BYN')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Сумма, BYN'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    await waitFor(() => expect(client.createExpense).toHaveBeenLastCalledWith(expect.objectContaining({ trip_id: null, currency: 'BYN', amount: '10' })));
    await screen.findByText('Расход сохранён.');
    expect(screen.getByLabelText('Расходы для')).toHaveValue('italy');
  });
  it('карточка будущей поездки сохраняет выбранный контекст при позднем ответе режима', async () => {
    const client = new ApiClient();
    vi.spyOn(client, 'trips').mockResolvedValue([trip]);
    let resolve!: (value: { trip: null; currencies: string[] }) => void;
    vi.spyOn(client, 'travelContext').mockReturnValue(new Promise(r => { resolve = r; }));
    vi.spyOn(client, 'categories').mockResolvedValue([{ name: 'Проживание', subcategories: [] }]);
    vi.spyOn(client, 'home').mockResolvedValue({ month: '2026-03', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] });
    render(<Home client={client} requestedTrip={trip} onDenied={vi.fn()} onTransactions={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText('Сумма, EUR')).toBeInTheDocument());
    resolve({ trip: null, currencies: ['BYN', 'EUR'] });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить расход' })).toBeEnabled());
    expect(screen.getByLabelText('Поездка расхода')).toHaveValue('italy');
  });
  it('редактирование валютного расхода отправляет исходную сумму, а не эквивалент', async () => {
    const client = new ApiClient();
    const row = { ...report.transactions[0], trip_id: 'italy', version: 'a'.repeat(64) };
    vi.spyOn(client, 'trips').mockResolvedValue([trip]);
    vi.spyOn(client, 'travelContext').mockResolvedValue({ trip: null, currencies: ['BYN', 'EUR'] });
    vi.spyOn(client, 'categories').mockResolvedValue([{ name: row.category, subcategories: [] }]);
    vi.spyOn(client, 'transactions').mockResolvedValue({ items: [row], total: 1, next_offset: null });
    vi.spyOn(client, 'participants').mockResolvedValue([]);
    vi.spyOn(client, 'transactionCategories').mockResolvedValue([row.category]);
    vi.spyOn(client, 'updateTransaction').mockResolvedValue(row);
    render(<Transactions client={client} user={user} onDenied={vi.fn()} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /Междугородний транспорт · 350/ }));
    expect(screen.getByLabelText('Сумма операции, EUR')).toHaveValue('100');
    fireEvent.change(screen.getByLabelText('Описание операции'), { target: { value: 'Уточнение билета' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }));
    await waitFor(() => expect(client.updateTransaction).toHaveBeenCalledWith('flight', expect.objectContaining({ amount: '100', currency: 'EUR', trip_id: 'italy', description: 'Уточнение билета' })));
  });
});
