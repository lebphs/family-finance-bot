import { StatisticsSummary } from '../api';

export const statisticsFixture: StatisticsSummary = {
  mode: 'range', months: ['2026-01', '2026-02', '2026-03'], author_id: null, unknown_author: false,
  total: '180', family_total: '180', count: 6,
  categories: [{ category: 'Транспорт', amount: '109.90' }, { category: 'Еда', amount: '70.10' }],
  monthly: [
    { month: '2026-01', total: '60', change: null, change_percent: null },
    { month: '2026-02', total: '0', change: '-60', change_percent: '-100' },
    { month: '2026-03', total: '120', change: '120', change_percent: null },
  ],
  participants: [
    { author_id: 42, author_name: 'Иван', total: '60', share_percent: '33.33', count: 3, average: '20', categories: [{ category: 'Еда', amount: '40.10' }, { category: 'Транспорт', amount: '19.90' }], monthly: [{ month: '2026-01', total: '30', change: null, change_percent: null }, { month: '2026-02', total: '0', change: '-30', change_percent: '-100' }, { month: '2026-03', total: '30', change: '30', change_percent: null }] },
    { author_id: 43, author_name: 'Анна', total: '110', share_percent: '61.11', count: 2, average: '55', categories: [{ category: 'Еда', amount: '20' }, { category: 'Транспорт', amount: '90' }], monthly: [{ month: '2026-01', total: '20', change: null, change_percent: null }, { month: '2026-02', total: '0', change: '-20', change_percent: '-100' }, { month: '2026-03', total: '90', change: '90', change_percent: null }] },
    { author_id: null, author_name: 'Автор не указан', total: '10', share_percent: '5.56', count: 1, average: '10', categories: [{ category: 'Еда', amount: '10' }], monthly: [{ month: '2026-01', total: '10', change: null, change_percent: null }, { month: '2026-02', total: '0', change: '-10', change_percent: '-100' }, { month: '2026-03', total: '0', change: '0', change_percent: null }] },
  ],
  available_participants: [{ author_id: 42, author_name: 'Иван' }, { author_id: 43, author_name: 'Анна' }, { author_id: null, author_name: 'Автор не указан' }],
  comparison: null,
};
export const emptyStatistics: StatisticsSummary = {
  ...statisticsFixture, mode: 'months', months: ['2026-10'], total: '0', family_total: '0', count: 0,
  categories: [], monthly: [{ month: '2026-10', total: '0', change: null, change_percent: null }], participants: [], available_participants: [],
};
