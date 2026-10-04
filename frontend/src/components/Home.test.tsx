import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, HomeSummary, Transaction } from '../api';
import { Home, validDate } from './Home';

const empty: HomeSummary = { month: '2026-10', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] };
const transaction: Transaction = { transaction_id: 'saved-id', date: '2026-10-03', amount: '12.50', category: 'Еда', description: 'Кафе', author_id: 42, author_name: 'Иван', created_at: null, updated_at: null };
function setup() {
  const client = new ApiClient();
  vi.spyOn(client, 'categories').mockResolvedValue([{ name: 'Еда', subcategories: ['Кафе'] }]);
  vi.spyOn(client, 'home').mockResolvedValue(empty);
  vi.spyOn(client, 'createExpense').mockResolvedValue(transaction);
  const onDenied = vi.fn(); const onTransactions = vi.fn();
  render(<Home client={client} onDenied={onDenied} onTransactions={onTransactions} />);
  return { client, onDenied, onTransactions };
}
async function fill(amount = '12,50') {
  await waitFor(() => expect(screen.getByRole('button', { name: 'Добавить расход: Еда' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Добавить расход: Еда' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить расход' })).toBeEnabled());
  fireEvent.change(screen.getByLabelText('Сумма, BYN'), { target: { value: amount } });
  fireEvent.change(screen.getByLabelText('Категория'), { target: { value: 'Еда' } });
  fireEvent.change(screen.getByLabelText('Подкатегория', { exact: true }), { target: { value: 'Кафе' } });
  fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-10-03' } });
}

describe('главная страница этапа 5', () => {
  it('открывает форму только по нажатию, выбирает категорию и сохраняет черновик при отмене', async () => {
    const { client } = setup();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Добавить расход: Еда' }));
    expect(screen.getByRole('dialog', { name: 'Новый расход' })).toBeInTheDocument();
    expect(screen.getByLabelText('Категория')).toHaveValue('Еда');
    expect(screen.getByLabelText('Сумма, BYN')).toHaveFocus();
    for (const key of ['1', '2', 'Десятичная запятая', '5', '0']) fireEvent.click(screen.getByRole('button', { name: key }));
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('12,50');
    fireEvent.click(screen.getByRole('button', { name: 'Удалить последнюю цифру' }));
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('12,5');
    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(client.createExpense).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Добавить расход: Еда' }));
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('12,5');
    fireEvent.click(screen.getByRole('button', { name: 'Очистить сумму' }));
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('');
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('поздняя первоначальная сводка не перезаписывает результат сохранения', async () => {
    const client = new ApiClient();
    vi.spyOn(client, 'categories').mockResolvedValue([{ name: 'Еда', subcategories: ['Кафе'] }]);
    let finish!: (value: HomeSummary) => void;
    vi.spyOn(client, 'home').mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValue({ ...empty, total: '12.50', recent: [transaction] });
    vi.spyOn(client, 'createExpense').mockResolvedValue(transaction);
    render(<Home client={client} onDenied={vi.fn()} onTransactions={vi.fn()} />);
    await fill();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    await screen.findByText('12,50');
    await act(async () => { finish(empty); });
    expect(screen.getByText('12,50')).toBeInTheDocument();
  });

  it('сохраняет сумму с запятой, подкатегорию и дату, обновляет сводку и последние расходы', async () => {
    const { client, onTransactions } = setup();
    await fill();
    vi.mocked(client.home).mockResolvedValue({ ...empty, total: '12.50', change: '12.50', categories: [{ category: 'Еда', amount: '12.50' }], recent: [transaction] });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    expect(await screen.findByText('Расход сохранён.')).toBeInTheDocument();
    expect(client.createExpense).toHaveBeenCalledWith({ request_id: expect.any(String), amount: '12.50', category: 'Еда', description: 'Кафе', date: '2026-10-03' });
    expect(await screen.findByText('12,50')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Расходы за текущий месяц' })).not.toBeInTheDocument();
    expect(screen.queryByText('Последние операции')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(client.home).toHaveBeenCalledTimes(2);
    expect(onTransactions).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Добавить расход' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'История расходов' })).not.toBeInTheDocument();
  });

  it.each(['0', '-1', 'abc', '1.234', 'Infinity', '10000000000'])('не отправляет некорректную сумму %s', async (amount) => {
    const { client } = setup(); await fill(amount);
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Введите положительную сумму');
    expect(client.createExpense).not.toHaveBeenCalled();
  });

  it('проверяет категорию и дату до запроса', async () => {
    const { client } = setup(); await fill();
    fireEvent.change(screen.getByLabelText('Категория'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Выберите категорию');
    fireEvent.change(screen.getByLabelText('Категория'), { target: { value: 'Еда' } });
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Укажите дату');
    expect(client.createExpense).not.toHaveBeenCalled();
    expect(validDate('2026-02-30')).toBe(false);
    expect(validDate('2024-02-29')).toBe(true);
    expect(validDate('03.10.2026')).toBe(false);
  });

  it('блокирует двойную отправку до завершения сохранения', async () => {
    const { client } = setup(); await fill();
    let finish!: (value: Transaction) => void;
    vi.mocked(client.createExpense).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const form = screen.getByLabelText('Сумма, BYN').closest('form')!;
    fireEvent.submit(form); fireEvent.submit(form);
    expect(client.createExpense).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Сохраняем…' })).toBeDisabled();
    await act(async () => { finish(transaction); });
  });

  it('сохраняет данные и ключ после сетевой ошибки, повторяет тот же запрос', async () => {
    const { client } = setup(); await fill();
    vi.mocked(client.createExpense).mockRejectedValueOnce(new ApiError(0, 'network_error', 'Нет соединения'));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    const retry = await screen.findByRole('button', { name: 'Повторить сохранение' });
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('12,50');
    expect(screen.getByLabelText('Сумма, BYN')).toBeDisabled();
    fireEvent.click(retry);
    await screen.findByText('Расход сохранён.');
    expect(vi.mocked(client.createExpense).mock.calls[0]).toEqual(vi.mocked(client.createExpense).mock.calls[1]);
  });

  it('при ошибке валидации сохраняет введённое и разрешает исправление', async () => {
    const { client } = setup(); await fill();
    vi.mocked(client.createExpense).mockRejectedValueOnce(new ApiError(422, 'validation_error', 'Проверьте данные'));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Проверьте данные');
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('12,50');
    expect(screen.getByLabelText('Сумма, BYN')).toBeEnabled();
  });

  it('повторяет неопределённое сохранение даже после исчезновения категорий', async () => {
    const client = new ApiClient();
    vi.spyOn(client, 'categories').mockResolvedValueOnce([{ name: 'Еда', subcategories: ['Кафе'] }])
      .mockResolvedValue([]);
    vi.spyOn(client, 'home').mockRejectedValueOnce(new ApiError(503, 'unavailable', 'Ошибка'))
      .mockResolvedValue(empty);
    vi.spyOn(client, 'createExpense').mockRejectedValueOnce(new ApiError(0, 'network_error', 'Нет соединения'))
      .mockResolvedValue(transaction);
    render(<Home client={client} onDenied={vi.fn()} onTransactions={vi.fn()} />);
    await fill();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    await screen.findByRole('button', { name: 'Повторить сохранение' });
    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await screen.findByText('Категории пока не настроены в таблице.');
    fireEvent.click(screen.getByRole('button', { name: 'Продолжить сохранение' }));
    const retry = screen.getByRole('button', { name: 'Повторить сохранение' });
    expect(retry).toBeEnabled();
    fireEvent.click(retry);
    await screen.findByText('Расход сохранён.');
    expect(vi.mocked(client.createExpense).mock.calls[0]).toEqual(vi.mocked(client.createExpense).mock.calls[1]);
  });

  it('не предлагает повторно сохранить после ошибки обновления сводки', async () => {
    const { client } = setup(); await fill();
    vi.mocked(client.home).mockRejectedValueOnce(new ApiError(503, 'request_failed', 'Недоступно'));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    expect(await screen.findByText('Расход сохранён, но сводку не удалось обновить.')).toBeInTheDocument();
    expect(screen.getByText('Расход сохранён.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(screen.queryByText('Расход сохранён, но сводку не удалось обновить.')).not.toBeInTheDocument());
    expect(client.createExpense).toHaveBeenCalledTimes(1);
  });

  it('повторяет загрузку категорий после ошибки', async () => {
    const client = new ApiClient();
    vi.spyOn(client, 'categories').mockRejectedValueOnce(new ApiError(503, 'unavailable', 'Ошибка')).mockResolvedValue([{ name: 'Еда', subcategories: [] }]);
    vi.spyOn(client, 'home').mockResolvedValue(empty);
    render(<Home client={client} onDenied={vi.fn()} onTransactions={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Добавить расход: Еда' })).toBeEnabled());
  });

  it('передаёт отзыв доступа родительскому экрану', async () => {
    const { client, onDenied } = setup(); await fill();
    vi.mocked(client.createExpense).mockRejectedValueOnce(new ApiError(403, 'access_denied', 'Нет доступа'));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    await waitFor(() => expect(onDenied).toHaveBeenCalledOnce());
  });
});
