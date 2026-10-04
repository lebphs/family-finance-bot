import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ParticipantMonthlyChart } from './ParticipantMonthlyChart';
import { statisticsFixture } from '../test/statistics';

it('сопоставляет суммы по месяцу, показывает имена и общую шкалу', () => {
  const participants = statisticsFixture.participants.map(person => ({ ...person, monthly: [...person.monthly].reverse() }));
  render(<ParticipantMonthlyChart months={statisticsFixture.months} participants={participants} />);
  expect(screen.getByRole('img', { name: 'Столбчатый график расходов по месяцам и участникам' })).toBeInTheDocument();
  const legend = screen.getByRole('list', { name: 'Участники графика' });
  expect(legend).toHaveTextContent('Иван'); expect(legend).toHaveTextContent('Анна');
  fireEvent.click(screen.getByText('Суммы по месяцам'));
  const table = screen.getByRole('table', { name: 'Расходы участников, BYN' });
  const january = within(table).getByRole('row', { name: '2026-01 — 60 30 20 10' });
  expect(january).toBeInTheDocument();
  expect(within(table).getByRole('row', { name: '2026-02 -100 % 0 0 0 0' })).toBeInTheDocument();
});

it('нулевые и отсутствующие месяцы не создают некорректную шкалу', () => {
  const { container } = render(<ParticipantMonthlyChart months={['2026-01', '2026-02']} participants={[{ ...statisticsFixture.participants[0], monthly: [] }]} />);
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
  expect(container.querySelectorAll('rect')).toHaveLength(2);
  for (const rect of container.querySelectorAll('rect')) expect(rect.getAttribute('height')).toBe('0');
});

it('показывает проценты и итог из API, включая рост и нулевую базу', () => {
  render(<ParticipantMonthlyChart months={['2026-01', '2026-02', '2026-03']} participants={statisticsFixture.participants} monthly={[
    { month: '2026-01', total: '100', change: null, change_percent: null },
    { month: '2026-02', total: '125', change: '25', change_percent: '25' },
    { month: '2026-03', total: '0', change: '-125', change_percent: '-100' },
  ]} />);
  fireEvent.click(screen.getByText('Суммы по месяцам'));
  const table = screen.getByRole('table');
  expect(within(table).getByRole('columnheader', { name: 'Изменение, %' })).toBeInTheDocument();
  expect(within(table).getByRole('row', { name: '2026-01 — 100 30 20 10' })).toBeInTheDocument();
  expect(within(table).getByRole('row', { name: '2026-02 +25 % 125 0 0 0' })).toBeInTheDocument();
  expect(within(table).getByRole('row', { name: '2026-03 -100 % 0 30 90 0' })).toBeInTheDocument();
});
