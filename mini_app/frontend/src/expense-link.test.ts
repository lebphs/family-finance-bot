import { describe, expect, it } from 'vitest';
import { readExpenseLaunch } from './expense-link';

describe('сумма из ссылки', () => {
  it.each([
    ['?amount=12.50', '12.50'], ['?amount=12%2C50', '12.50'],
    ['?amount=1', '1'], ['?amount=9999999999.99', '9999999999.99'],
    ['?tgWebAppStartParam=expense_12_50', '12.50'],
    ['?startapp=expense_12_50', '12.50'], ['?startapp=expense_12', '12'],
  ])('читает %s', (query, amount) => {
    expect(readExpenseLaunch(query, '')).toEqual({ amount, error: '' });
  });

  it('читает start_param SDK и отдаёт ему приоритет', () => {
    expect(readExpenseLaunch('?amount=10&tgWebAppStartParam=expense_20', 'start_param=expense_30_25'))
      .toEqual({ amount: '30.25', error: '' });
  });

  it.each(['', '0', '-1', 'NaN', 'Infinity', '1e2', '1.234', '10000000000', '1 234', '<script>', '12BYN'])('отклоняет сумму %s', amount => {
    expect(readExpenseLaunch(`?amount=${encodeURIComponent(amount)}`, ''))
      .toEqual({ amount: '', error: expect.stringContaining('некорректная сумма') });
  });

  it.each(['expense_', 'expense_-1', 'expense_1_234', 'expense_1_2_3'])('отклоняет payload %s', start => {
    expect(readExpenseLaunch(`?tgWebAppStartParam=${start}`, '')?.error).toBeTruthy();
  });

  it.each(['', '?other=10', '?startapp=other_command'])('не открывает расход без суммы: %s', query => {
    expect(readExpenseLaunch(query, '')).toBeNull();
  });
});
