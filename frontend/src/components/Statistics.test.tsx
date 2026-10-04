import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, StatisticsSummary } from '../api';
import { statisticsFixture, emptyStatistics } from '../test/statistics';
import { Statistics } from './Statistics';

function setup(data = statisticsFixture) {
  const client = new ApiClient();
  vi.spyOn(client, 'statistics').mockResolvedValue(data);
  const onDenied = vi.fn();
  return { client, onDenied };
}
const openFilters = () => { const button = screen.getByRole('button', { name: 'Фильтры' }); if (button.getAttribute('aria-expanded') === 'false') fireEvent.click(button); };
const apply = () => fireEvent.click(screen.getByRole('button', { name: 'Показать статистику' }));

describe('этап 7: статистика', () => {
  it('показывает загрузку, итоги, категории, пустой месяц и метрики участников', async () => {
    render(<Statistics {...setup()} />);
    expect(screen.getByText('Загружаем статистику')).toBeInTheDocument();
    expect(await screen.findByRole('region', { name: 'Расходы по месяцам и участникам' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Диаграмма категорий' })).toHaveTextContent('109,90 BYN');
    expect(screen.queryByRole('region', { name: 'Вся семья' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Суммы по месяцам'));
    expect(screen.getByRole('table')).toHaveTextContent('-100 %');
    const summary = screen.getByText(/Иван · 60,00 BYN · доля: 33,33/);
    fireEvent.click(summary);
    const details = summary.closest('details')!;
    expect(within(details).getByText('Количество операций: 3')).toBeInTheDocument();
    expect(within(details).getByText('Средняя сумма: 20,00 BYN')).toBeInTheDocument();
    expect(within(details).getByRole('list', { name: 'Динамика: Иван' })).toHaveTextContent('30,00 BYN');
    expect(screen.getByText(/Автор не указан · 10,00 BYN · доля: 5,56/)).toBeInTheDocument();
  });

  it.each(['1', '2', '3', '6', '12'])('передаёт период %s', async (months) => {
    const props = setup(); render(<Statistics {...props} />);
    await screen.findByRole('region', { name: 'Расходы по месяцам и участникам' });
    openFilters(); fireEvent.change(screen.getByLabelText('Период статистики'), { target: { value: months } }); apply();
    await waitFor(() => expect(props.client.statistics).toHaveBeenLastCalledWith({ mode: 'months', months }, expect.any(AbortSignal)));
  });

  it('передаёт диапазон и переключает семью, участника и неизвестного автора', async () => {
    const props = setup(); render(<Statistics {...props} />); await screen.findByRole('region', { name: 'Расходы по месяцам и участникам' });
    openFilters(); fireEvent.change(screen.getByLabelText('Период статистики'), { target: { value: 'range' } });
    openFilters(); fireEvent.change(screen.getByLabelText('Начальный месяц'), { target: { value: '2026-01' } });
    openFilters(); fireEvent.change(screen.getByLabelText('Конечный месяц'), { target: { value: '2026-03' } });
    for (const [value, extra] of [['42', { author_id: '42' }], ['unknown', { unknown_author: 'true' }], ['', {}]] as const) {
      openFilters(); fireEvent.change(screen.getByLabelText('Участник статистики'), { target: { value } }); apply();
      await waitFor(() => expect(props.client.statistics).toHaveBeenLastCalledWith({ mode: 'range', month_from: '2026-01', month_to: '2026-03', ...extra }, expect.any(AbortSignal)));
      await screen.findByRole('region', { name: 'Расходы по месяцам и участникам' });
    }
  });

  it('сравнивает выбранные месяцы и объясняет неопределённый процент', async () => {
    const props = setup({ ...statisticsFixture, comparison: { month_from: '2026-02', month_to: '2026-03', from_total: '0', to_total: '120', change: '120', change_percent: null } });
    render(<Statistics {...props} />); await screen.findByRole('region', { name: 'Расходы по месяцам и участникам' });
    const card = screen.getByRole('region', { name: 'Сравнение месяцев' });
    expect(card).toHaveTextContent('Разница: 120,00 BYN'); expect(card).toHaveTextContent('Изменение: не определён');
    openFilters(); fireEvent.change(screen.getByLabelText('Период статистики'), { target: { value: 'compare' } });
    openFilters(); fireEvent.change(screen.getByLabelText('Базовый месяц'), { target: { value: '2026-02' } });
    openFilters(); fireEvent.change(screen.getByLabelText('Сравниваемый месяц'), { target: { value: '2026-03' } }); apply();
    await waitFor(() => expect(props.client.statistics).toHaveBeenLastCalledWith({ mode: 'compare', compare_from: '2026-02', compare_to: '2026-03' }, expect.any(AbortSignal)));
  });

  it('отклоняет перевёрнутый диапазон и одинаковые месяцы до запроса', async () => {
    const props = setup(); render(<Statistics {...props} />); await screen.findByRole('region', { name: 'Расходы по месяцам и участникам' });
    openFilters(); fireEvent.change(screen.getByLabelText('Период статистики'), { target: { value: 'range' } });
    openFilters(); fireEvent.change(screen.getByLabelText('Начальный месяц'), { target: { value: '2026-03' } });
    openFilters(); fireEvent.change(screen.getByLabelText('Конечный месяц'), { target: { value: '2026-01' } }); apply();
    expect(screen.getByRole('alert')).toHaveTextContent('начало должно быть не позже');
    openFilters(); fireEvent.change(screen.getByLabelText('Период статистики'), { target: { value: 'compare' } });
    for (const label of ['Базовый месяц', 'Сравниваемый месяц']) { openFilters(); fireEvent.change(screen.getByLabelText(label), { target: { value: '2026-01' } }); }
    apply(); expect(screen.getByRole('alert')).toHaveTextContent('два разных месяца');
    expect(props.client.statistics).toHaveBeenCalledTimes(1);
  });

  it('показывает пустое состояние без NaN и Infinity', async () => {
    const { container } = render(<Statistics {...setup(emptyStatistics)} />);
    expect(await screen.findByText('За выбранный период расходов нет.')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Вся семья' })).not.toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
  });

  it('сохраняет фильтры и позволяет повторить запрос после ошибки', async () => {
    const props = setup(); vi.mocked(props.client.statistics).mockRejectedValueOnce(new ApiError(503, 'request_failed', 'Не удалось загрузить данные.'));
    render(<Statistics {...props} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('region', { name: 'Расходы по месяцам и участникам' })).toBeInTheDocument();
    expect(props.client.statistics).toHaveBeenCalledTimes(2);
  });

  it.each([401, 403])('обрабатывает отказ %i', async (status) => {
    const props = setup(); vi.mocked(props.client.statistics).mockRejectedValue(new ApiError(status, 'access_denied', 'Нет доступа'));
    render(<Statistics {...props} />);
    await waitFor(() => expect(props.onDenied).toHaveBeenCalledOnce());
    expect(screen.queryByRole('region', { name: 'Расходы по месяцам и участникам' })).not.toBeInTheDocument();
  });

  it('отменяет старые запросы и игнорирует поздний ответ', async () => {
    const props = setup(); let resolve!: (data: StatisticsSummary) => void;
    vi.mocked(props.client.statistics).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const { unmount } = render(<Statistics {...props} />);
    const firstSignal = vi.mocked(props.client.statistics).mock.calls[0][1]!;
    openFilters(); fireEvent.change(screen.getByLabelText('Период статистики'), { target: { value: '12' } }); apply();
    await screen.findByRole('region', { name: 'Расходы по месяцам и участникам' }); expect(firstSignal.aborted).toBe(true);
    await act(async () => resolve(emptyStatistics));
    expect(screen.getByRole('region', { name: 'Расходы по месяцам и участникам' })).toBeInTheDocument();
    expect(screen.queryByText('За выбранный период расходов нет.')).not.toBeInTheDocument();
    const latestSignal = vi.mocked(props.client.statistics).mock.calls[1][1]!;
    unmount(); expect(latestSignal.aborted).toBe(true);
  });
});
