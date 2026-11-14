import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { emptyStatistics } from './test/statistics';
import { App } from './App';
import { ApiClient, ApiError } from './api';

const user = { telegram_user_id: 42, display_name: 'Иван', role: 'member' as const };
function client() {
  const api = new ApiClient();
  vi.spyOn(api, 'trips').mockResolvedValue([]);
  vi.spyOn(api, 'travelContext').mockResolvedValue({ trip: null, currencies: ['BYN', 'EUR'] });
  vi.spyOn(api, 'statistics').mockResolvedValue(emptyStatistics);
  vi.spyOn(api, 'reminders').mockResolvedValue({ reminder_enabled: false, reminder_time: '22:00', reminder_days: [0,1,2,3,4,5,6], timezone: 'Europe/Minsk', chat_connected: false });
  vi.spyOn(api, 'me').mockResolvedValue(user);
  vi.spyOn(api, 'categories').mockResolvedValue([]);
  vi.spyOn(api, 'transactions').mockResolvedValue({ items: [], total: 0, next_offset: null });
  vi.spyOn(api, 'participants').mockResolvedValue([]);
  vi.spyOn(api, 'transactionCategories').mockResolvedValue([]);
  vi.spyOn(api, 'home').mockResolvedValue({ month: '2026-10', total: '0', previous_total: '0', change: '0', change_percent: null, categories: [], recent: [] });
  return api;
}

describe('каркас Mini App', () => {
  afterEach(() => window.history.replaceState(null, '', '/'));

  it.each(['?amount=12%2C50', '?tgWebAppStartParam=expense_12_50'])('открывает расход из %s после проверки доступа и сохраняет только по нажатию', async query => {
    window.history.replaceState(null, '', query);
    const api = client();
    vi.mocked(api.categories).mockResolvedValue([{ name: 'Еда', subcategories: [] }]);
    const create = vi.spyOn(api, 'createExpense').mockResolvedValue({ transaction_id: 'link-expense', date: '2026-11-14', amount: '12.50', category: 'Еда', description: '', author_id: 42, author_name: 'Иван', created_at: null, updated_at: null });
    render(<App client={api} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await screen.findByRole('dialog', { name: 'Новый расход' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить расход' })).toBeEnabled());
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('12.50');
    expect(screen.getByLabelText('Категория', { exact: true })).toHaveValue('');
    expect(create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));
    fireEvent.click(screen.getByRole('button', { name: 'Транзакции' }));
    fireEvent.click(screen.getByRole('button', { name: 'Главная' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Добавить расход: Еда' }));
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('12.50');
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить расход' }));
    await screen.findByText('Расход сохранён.');
    expect(create).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ amount: '12.50', category: 'Еда', currency: 'BYN', trip_id: null }));
    fireEvent.click(screen.getByRole('button', { name: 'Добавить расход: Еда' }));
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('');
  });

  it('позволяет исправить некорректную сумму из ссылки', async () => {
    window.history.replaceState(null, '', '?amount=-10');
    render(<App client={client()} />);
    await screen.findByRole('dialog', { name: 'Новый расход' });
    expect(screen.getByRole('alert')).toHaveTextContent('В ссылке указана некорректная сумма');
    expect(screen.getByLabelText('Сумма, BYN')).toHaveValue('');
  });

  it('ссылка с суммой не обходит проверку доступа', async () => {
    window.history.replaceState(null, '', '?amount=12.50');
    const api = client();
    vi.mocked(api.me).mockRejectedValue(new ApiError(403, 'access_denied', 'Нет доступа'));
    render(<App client={api} />);
    await screen.findByText('Нет доступа');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.categories).not.toHaveBeenCalled();
  });

  it('показывает загрузку до завершения проверки доступа', () => {
    const api = client();
    vi.mocked(api.me).mockReturnValue(new Promise(() => {}));
    render(<App client={api} />);
    expect(screen.getByText('Загружаем приложение')).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it.each([401, 403])('при отказе %i показывает только экран доступа', async (status) => {
    const api = client();
    vi.mocked(api.me).mockRejectedValue(new ApiError(status, 'access_denied', 'Нет доступа'));
    render(<App client={api} />);
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(screen.queryByText(/Иван/)).not.toBeInTheDocument();
    expect(api.categories).not.toHaveBeenCalled();
  });

  it('позволяет повторить загрузку после временной ошибки', async () => {
    const api = client();
    vi.mocked(api.me).mockRejectedValueOnce(new ApiError(503, 'request_failed', 'Попробуйте ещё раз.'));
    render(<App client={api} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('navigation')).toBeInTheDocument();
    expect(api.me).toHaveBeenCalledTimes(2);
  });

  it('переключает все пять разделов и показывает пустое состояние без выдуманных операций', async () => {
    render(<App client={client()} />);
    const nav = await screen.findByRole('navigation', { name: 'Основная навигация' });
    expect(nav.querySelectorAll('button')).toHaveLength(5);
    for (const name of ['Транзакции', 'Статистика', 'Поездки', 'Настройки']) {
      const button = screen.getByRole('button', { name });
      fireEvent.click(button);
      expect(button).toHaveAttribute('aria-current', 'page');
      if (name === 'Транзакции') expect(await screen.findByText('По выбранным условиям операций нет.')).toBeInTheDocument();
      else if (name === 'Статистика') expect(await screen.findByText('За выбранный период расходов нет.')).toBeInTheDocument();
      else if (name === 'Поездки') expect(await screen.findByText('Поездок пока нет. Можно создать будущую поездку и записывать билеты заранее.')).toBeInTheDocument();
      else expect(await screen.findByText('Персональные напоминания')).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole('button', { name: 'Главная' }));
    expect(screen.getByText('Нажмите на категорию, чтобы добавить расход')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Настройки' }));
    expect(screen.getByRole('region', { name: 'Ваш профиль' })).toHaveTextContent('Участник семьи');
  });

  it('отменяет запрос при размонтировании и не показывает поздний результат', async () => {
    const api = client();
    const { unmount } = render(<App client={api} />);
    const signal = vi.mocked(api.me).mock.calls[0][0]!;
    unmount();
    await waitFor(() => expect(signal.aborted).toBe(true));
  });
});
