import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, CurrentUser, Transaction } from '../api';
import { Transactions } from './Transactions';

const user: CurrentUser = { telegram_user_id: 42, display_name: 'Иван', role: 'member' };
const own: Transaction = { transaction_id: 'own', version: 'a'.repeat(64), date: '2026-10-04', amount: '12.50', category: 'Еда', description: 'Кафе', author_id: 42, author_name: 'Иван', created_at: null, updated_at: null };
const other: Transaction = { ...own, transaction_id: 'other', author_id: 43, author_name: 'Анна', description: 'Магазин' };
function setup(items = [own, other], current = user) {
  const client = new ApiClient();
  vi.spyOn(client, 'categories').mockResolvedValue([{ name: 'Еда', subcategories: ['Кафе'] }, { name: 'Транспорт', subcategories: [] }]);
  vi.spyOn(client, 'participants').mockResolvedValue([{ author_id: 42, author_name: 'Иван' }, { author_id: 43, author_name: 'Анна' }, { author_id: null, author_name: 'Автор не указан' }]);
  vi.spyOn(client, 'transactionCategories').mockResolvedValue(['Старая категория']);
  vi.spyOn(client, 'transactions').mockResolvedValue({ items, total: items.length, next_offset: null });
  vi.spyOn(client, 'transaction').mockResolvedValue(own);
  vi.spyOn(client, 'updateTransaction').mockResolvedValue({ ...own, amount: '15' });
  vi.spyOn(client, 'deleteTransaction').mockResolvedValue(undefined);
  const denied = vi.fn(); const changed = vi.fn();
  const view = render(<Transactions client={client} user={current} onDenied={denied} onChanged={changed} />);
  return { client, denied, changed, ...view };
}
const pullRefresh = () => { const target = screen.getByRole('region', { name: 'Список транзакций' }); fireEvent.touchStart(target, { touches: [{ clientX: 100, clientY: 100 }] }); fireEvent.touchMove(target, { touches: [{ clientX: 100, clientY: 270 }] }); fireEvent.touchEnd(target); };
const open = async (name = /Кафе/) => fireEvent.click(await screen.findByRole('button', { name }));

describe('управление транзакциями', () => {
  it('передаёт фильтры, поддерживает старые категории и сбрасывает условия', async () => {
    const { client } = setup(); await screen.findByText('Найдено операций: 2');
    expect(screen.queryByRole('region', { name: 'Фильтры транзакций' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Фильтры' }));
    fireEvent.change(screen.getByLabelText('Период с'), { target: { value: '2026-08-01' } });
    fireEvent.change(screen.getByLabelText('Период по'), { target: { value: '2026-10-31' } });
    fireEvent.change(screen.getByLabelText('Категория фильтра'), { target: { value: 'Старая категория' } });
    fireEvent.change(screen.getByLabelText('Участник'), { target: { value: '43' } });
    fireEvent.change(screen.getByLabelText('Поиск по описанию'), { target: { value: 'кафе' } });
    fireEvent.click(screen.getByRole('button', { name: 'Применить фильтры' }));
    await waitFor(() => expect(client.transactions).toHaveBeenLastCalledWith({ date_from: '2026-08-01', date_to: '2026-10-31', category: 'Старая категория', author_id: '43', search: 'кафе' }, expect.any(AbortSignal)));
    await screen.findByText('Найдено операций: 2'); fireEvent.click(screen.getByRole('button', { name: /Фильтры/ })); fireEvent.click(screen.getByRole('button', { name: 'Сбросить' }));
    await waitFor(() => expect(client.transactions).toHaveBeenLastCalledWith({}, expect.any(AbortSignal)));
    await screen.findByText('Найдено операций: 2');
    fireEvent.change(screen.getByLabelText('Участник'), { target: { value: 'unknown' } });
    fireEvent.click(screen.getByRole('button', { name: 'Применить фильтры' }));
    await waitFor(() => expect(client.transactions).toHaveBeenLastCalledWith({ unknown_author: 'true' }, expect.any(AbortSignal)));
  });

  it('показывает пустой результат и позволяет повторить ошибку загрузки', async () => {
    const { client } = setup([]); await screen.findByText('По выбранным условиям операций нет.');
    vi.mocked(client.transactions).mockRejectedValueOnce(new ApiError(503, 'request_failed', 'Ошибка'));
    pullRefresh();
    fireEvent.click(await screen.findByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('По выбранным условиям операций нет.')).toBeInTheDocument();
  });

  it('загружает следующую страницу, сохраняя предыдущие операции', async () => {
    const { client } = setup([own]);
    vi.mocked(client.transactions).mockResolvedValueOnce({ items: [own], total: 2, next_offset: 1 }).mockResolvedValueOnce({ items: [other], total: 2, next_offset: null });
    await screen.findByText('Найдено операций: 1'); pullRefresh();
    fireEvent.click(await screen.findByRole('button', { name: 'Загрузить ещё' }));
    expect(await screen.findByRole('button', { name: /Магазин/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Кафе/ })).toBeInTheDocument();
    expect(client.transactions).toHaveBeenLastCalledWith({ offset: '1' });
  });

  it('редактирует по ID и версии, защищает двойную отправку и обновляет сводку', async () => {
    const { client, changed } = setup(); await open();
    fireEvent.change(screen.getByLabelText('Сумма операции, BYN'), { target: { value: '15,00' } });
    let finish!: (item: Transaction) => void;
    vi.mocked(client.updateTransaction).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const save = screen.getByRole('button', { name: 'Сохранить изменения' }); fireEvent.click(save); fireEvent.click(save);
    expect(client.updateTransaction).toHaveBeenCalledTimes(1);
    expect(client.updateTransaction).toHaveBeenCalledWith('own', { version: own.version, date: own.date, amount: '15.00', category: own.category, description: own.description });
    finish({ ...own, amount: '15' }); await screen.findByText('Операция изменена.');
    expect(changed).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(client.transactions).toHaveBeenCalledTimes(2));
  });

  it('проверяет сумму перед запросом', async () => {
    const { client } = setup(); await open();
    fireEvent.change(screen.getByLabelText('Сумма операции, BYN'), { target: { value: '-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Проверьте'); expect(client.updateTransaction).not.toHaveBeenCalled();
  });

  it('удаляет после подтверждения, отмена не отправляет запрос', async () => {
    const { client, changed } = setup(); await open(); fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    expect(client.deleteTransaction).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole('button', { name: 'Отмена удаления' }));
    expect(client.deleteTransaction).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить удаление' })); await screen.findByText('Операция удалена.');
    expect(client.deleteTransaction).toHaveBeenCalledWith('own', own.version); expect(changed).toHaveBeenCalledTimes(1);
  });

  it.each([409, 503, 0])('при ошибке %i сохраняет черновик и требует обновления', async (status) => {
    const { client } = setup(); vi.mocked(client.updateTransaction).mockRejectedValue(new ApiError(status, 'failed', 'Результат неизвестен'));
    await open();
    fireEvent.change(screen.getByLabelText('Описание операции'), { target: { value: 'Мой текст' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' })); await screen.findByRole('button', { name: 'Загрузить актуальную операцию' });
    expect(screen.getByLabelText('Описание операции')).toHaveValue('Мой текст');
    expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Загрузить актуальную операцию' }));
    expect(await screen.findByRole('button', { name: 'Сохранить изменения' })).toBeInTheDocument(); expect(client.transaction).toHaveBeenCalledWith('own');
  });

  it('обрабатывает уже удалённую операцию', async () => {
    const { client } = setup(); vi.mocked(client.deleteTransaction).mockRejectedValue(new ApiError(404, 'not_found', 'Удалена'));
    vi.mocked(client.transaction).mockRejectedValue(new ApiError(404, 'not_found', 'Удалена'));
    await open(); fireEvent.click(screen.getByRole('button', { name: 'Удалить' })); fireEvent.click(screen.getByRole('button', { name: 'Подтвердить удаление' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Загрузить актуальную операцию' })); await screen.findByText('Операция уже удалена.');
    expect(screen.queryByRole('dialog', { name: 'Просмотр расхода' })).not.toBeInTheDocument();
  });

  it('показывает чужую операцию без кнопок изменения', async () => {
    setup(); await open(/Магазин/); expect(screen.getByRole('dialog', { name: 'Просмотр расхода' })).toHaveTextContent('Анна');
    expect(screen.queryByRole('button', { name: 'Сохранить изменения' })).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Удалить' })).not.toBeInTheDocument();
  });
  it('администратор может менять старую операцию без автора', async () => {
    setup([{ ...own, author_id: null, author_name: 'Автор не указан' }], { ...user, role: 'admin' }); await open();
    expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeInTheDocument();
  });
  it('строки без ID доступны для просмотра с объяснением', async () => {
    setup([{ ...own, transaction_id: null }], { ...user, role: 'admin' }); await open();
    expect(screen.getByText('Для изменения требуется миграция постоянных ID.')).toBeInTheDocument();
  });
  it('отказ API закрывает доступ', async () => {
    const { client, denied } = setup(); vi.mocked(client.transactions).mockRejectedValueOnce(new ApiError(403, 'access_denied', 'Нет доступа'));
    await screen.findByText('Найдено операций: 2'); pullRefresh();
    await waitFor(() => expect(denied).toHaveBeenCalled());
  });
});

it('нажатие сразу открывает редактор, Escape возвращает фокус без сохранения', async () => {
  const { client } = setup();
  const row = await screen.findByRole('button', { name: /Кафе/ }); row.focus(); fireEvent.click(row);
  expect(screen.getByRole('dialog', { name: 'Редактировать расход' })).toBeInTheDocument();
  expect(screen.getByLabelText('Сумма операции, BYN')).toHaveValue('12.50');
  expect(screen.getByLabelText('Сумма операции, BYN')).toHaveFocus();
  fireEvent.click(screen.getByRole('button', { name: 'Очистить сумму' }));
  for (const key of ['2', 'Десятичная запятая', '5']) fireEvent.click(screen.getByRole('button', { name: key }));
  expect(screen.getByLabelText('Сумма операции, BYN')).toHaveValue('2,5');
  const dialog = screen.getByRole('dialog');
  screen.getByRole('button', { name: 'Удалить' }).focus(); fireEvent.keyDown(dialog, { key: 'Tab' });
  expect(screen.getByRole('button', { name: 'Закрыть операцию' })).toHaveFocus();
  fireEvent.keyDown(dialog, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(row).toHaveFocus();
  expect(client.updateTransaction).not.toHaveBeenCalled(); expect(client.deleteTransaction).not.toHaveBeenCalled();
});
