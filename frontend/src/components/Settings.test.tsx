import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from '../api';
import { Settings } from './Settings';

const user = { telegram_user_id: 1, display_name: 'Иван', role: 'member' as const };
const defaults = { reminder_enabled: false, reminder_time: '22:00', reminder_days: [0,1,2,3,4,5,6], timezone: 'Europe/Minsk', chat_connected: false };
function client() {
  const api = new ApiClient();
  vi.spyOn(api, 'reminders').mockResolvedValue(defaults);
  vi.spyOn(api, 'saveReminders').mockImplementation(async input => ({ ...input, chat_connected: false }));
  vi.spyOn(api, 'users').mockResolvedValue([{ ...user, active: true }]);
  vi.spyOn(api, 'createUser').mockImplementation(async input => input);
  vi.spyOn(api, 'updateUser').mockResolvedValue({ ...user, active: false });
  return api;
}

describe('настройки этапа 8', () => {
  it('загружает значения и сохраняет персональное расписание', async () => {
    const api = client();
    render(<Settings client={api} user={user} onDenied={vi.fn()} />);
    expect(screen.getByText('Загружаем настройки…')).toBeInTheDocument();
    expect(await screen.findByLabelText('Время')).toHaveValue('22:00');
    expect(screen.getByLabelText('Часовой пояс')).toHaveValue('Europe/Minsk');
    expect(screen.getByText(/отправьте \/start/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Включить напоминания'));
    fireEvent.change(screen.getByLabelText('Время'), { target: { value: '09:30' } });
    fireEvent.click(screen.getByLabelText('Вс'));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    expect(await screen.findByText('Настройки сохранены')).toBeInTheDocument();
    expect(api.saveReminders).toHaveBeenCalledWith({ reminder_enabled: true, reminder_time: '09:30', reminder_days: [0,1,2,3,4,5], timezone: 'Europe/Minsk' });
    expect(api.users).not.toHaveBeenCalled();
  });

  it('блокирует двойное нажатие и сохраняет форму при ошибке', async () => {
    const api = client();
    let reject!: (e: Error) => void;
    vi.mocked(api.saveReminders).mockReturnValue(new Promise((_, no) => { reject = no; }));
    render(<Settings client={api} user={user} onDenied={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText('Время'), { target: { value: '12:45' } });
    const button = screen.getByRole('button', { name: 'Сохранить настройки' });
    fireEvent.click(button); fireEvent.click(button);
    expect(api.saveReminders).toHaveBeenCalledTimes(1);
    reject(new ApiError(503, 'failed', 'Не удалось сохранить настройки.'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось сохранить настройки.');
    expect(screen.getByLabelText('Время')).toHaveValue('12:45');
    expect(screen.getByRole('button', { name: 'Сохранить настройки' })).toBeEnabled();
  });

  it('не отправляет пустой набор дней', async () => {
    const api = client();
    render(<Settings client={api} user={user} onDenied={vi.fn()} />);
    await screen.findByLabelText('Время');
    for (const day of ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']) fireEvent.click(screen.getByLabelText(day));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Выберите хотя бы один день');
    expect(api.saveReminders).not.toHaveBeenCalled();
  });

  it('обрабатывает отказ доступа и повтор загрузки', async () => {
    const api = client();
    const denied = vi.fn();
    vi.mocked(api.reminders).mockRejectedValueOnce(new ApiError(503,'failed','Не удалось загрузить настройки.'));
    render(<Settings client={api} user={user} onDenied={denied} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Повторить' }));
    await screen.findByLabelText('Время');
    vi.mocked(api.saveReminders).mockRejectedValueOnce(new ApiError(403,'denied','Нет доступа'));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }));
    await waitFor(() => expect(denied).toHaveBeenCalledOnce());
  });

  it('позволяет администратору добавить участника и подтверждает отключение', async () => {
    const api = client();
    const confirm = vi.spyOn(window,'confirm').mockReturnValue(false);
    render(<Settings client={api} user={{ ...user, role: 'admin' }} onDenied={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Отключить доступ: Иван' }));
    expect(api.updateUser).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Отключить доступ: Иван' }));
    expect(await screen.findByText(/Доступ отключён/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Telegram ID'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Имя'), { target: { value: 'Анна' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить участника' }));
    expect(await screen.findByText(/Анна · Участник/)).toBeInTheDocument();
    expect(api.createUser).toHaveBeenCalledWith({ telegram_user_id: 2, display_name: 'Анна', role: 'member', active: true });
  });
});
