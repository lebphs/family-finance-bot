import { getTelegram } from './telegram';

export type ExpenseLaunch = { amount: string; error: string };

// Launch data only fills a draft. Authentication and saving use the usual API flow.
export function readExpenseLaunch(search = window.location.search, initData = getTelegram()?.initData ?? ''): ExpenseLaunch | null {
  const query = new URLSearchParams(search);
  const start = new URLSearchParams(initData).get('start_param')
    ?? query.get('tgWebAppStartParam') ?? query.get('startapp');
  const raw = start?.startsWith('expense_') ? start.slice('expense_'.length).replace('_', '.') : query.get('amount');
  if (raw === null) return null;
  const amount = raw.trim().replace(',', '.');
  if (!/^\d{1,10}(?:\.\d{1,2})?$/.test(amount) || Number(amount) <= 0 || Number(amount) >= 10_000_000_000) {
    return { amount: '', error: 'В ссылке указана некорректная сумма. Введите положительную сумму, не более двух знаков после запятой.' };
  }
  return { amount, error: '' };
}
