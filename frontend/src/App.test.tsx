import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { emptyStatistics } from './test/statistics';
import { App } from './App';
import { ApiClient, ApiError } from './api';

const user = { telegram_user_id: 42, display_name: 'Иван', role: 'member' as const };
function client() {
  const api = new ApiClient();
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

  it('переключает все четыре раздела и показывает пустое состояние без выдуманных операций', async () => {
    render(<App client={client()} />);
    const nav = await screen.findByRole('navigation', { name: 'Основная навигация' });
    expect(nav.querySelectorAll('button')).toHaveLength(4);
    for (const name of ['Транзакции', 'Статистика', 'Настройки']) {
      const button = screen.getByRole('button', { name });
      fireEvent.click(button);
      expect(button).toHaveAttribute('aria-current', 'page');
      if (name === 'Транзакции') expect(await screen.findByText('По выбранным условиям операций нет.')).toBeInTheDocument();
      else if (name === 'Статистика') expect(await screen.findByText('За выбранный период расходов нет.')).toBeInTheDocument();
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
