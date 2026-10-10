import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ExpenseWheel } from './ExpenseWheel';
import { HomeSummary } from '../api';

const names = ['Продукты', 'Здоровье', 'Подарки', 'Спорт', 'Еда вне дома', 'Машина', 'Транспорт', 'Развлечения', 'Одежда', 'Дом', 'Уход за собой', 'Развитие', 'Счета'];
const categories = names.map(name => ({ name, subcategories: [] }));
const summary: HomeSummary = { month: '2026-10', total: '25', previous_total: '0', change: '25', change_percent: null, recent: [], categories: [{ category: 'Подарки', amount: '15' }, { category: 'Спорт', amount: '5' }, { category: 'Еда вне дома', amount: '5' }] };

it('включает тринадцатую категорию в тот же круг и сохраняет выбор', () => {
  const choose = vi.fn();
  const { container } = render(<ExpenseWheel categories={categories} summary={summary} onCategory={choose} disabled={false} />);
  expect(container.querySelectorAll('.expense-wheel .orbit-category')).toHaveLength(13);
  fireEvent.click(screen.getByRole('button', { name: 'Добавить расход: Счета' }));
  expect(choose).toHaveBeenCalledWith('Счета');
  const markers = [...container.querySelectorAll<HTMLElement>('.orbit-label .category-marker')].map(item => item.style.background);
  expect(new Set(markers).size).toBe(13);
});

it('цвета секторов соответствуют категориям и легенде даже при другом порядке сумм', () => {
  const { container } = render(<ExpenseWheel categories={categories} summary={summary} onCategory={vi.fn()} disabled={false} />);
  const legend = screen.getByRole('list', { name: 'Категории на круговой диаграмме' });
  const rows = within(legend).getAllByRole('listitem');
  const circles = [...container.querySelectorAll('.donut circle')].slice(1);
  for (const [index, entry] of summary.categories.entries()) {
    const category = screen.getByRole('button', { name: `Добавить расход: ${entry.category}` });
    const marker = category.querySelector<HTMLElement>('.category-marker')!;
    const normalized = document.createElement('span'); normalized.style.color = circles[index].getAttribute('stroke')!;
    expect(normalized.style.color).toBe(category.style.color);
    expect(rows[index].querySelector<HTMLElement>('.category-marker')!.style.background).toBe(marker.style.background);
    expect(rows[index]).toHaveTextContent(`${entry.category}${Number(entry.amount).toFixed(2).replace('.', ',')} BYN`);
  }
  expect(container.querySelectorAll('.donut-share')).toHaveLength(3);
});

it('при нулевых расходах не показывает ложные сектора и суммы', () => {
  const { container } = render(<ExpenseWheel categories={categories} summary={{ ...summary, total: '0', categories: [] }} onCategory={vi.fn()} disabled />);
  expect(screen.queryByRole('list')).not.toBeInTheDocument();
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
  expect(screen.getByRole('button', { name: 'Добавить расход: Счета' })).toBeDisabled();
});
