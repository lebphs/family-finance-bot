import { ApiClient, Category, ReminderResponse, StatisticsSummary, Transaction } from './api';

// This transport never calls fetch: all preview reads and writes stay in memory.
export function createPreviewClient(): ApiClient {
  const user = { telegram_user_id: 42, display_name: 'Иван', role: 'member' as const };
  const month = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Minsk' }).format(new Date()).slice(0, 7);
  const previous = new Date(`${month}-01T12:00:00`);
  previous.setMonth(previous.getMonth() - 1);
  const previousMonth = previous.toLocaleDateString('sv-SE').slice(0, 7);
  const categories: Category[] = [
    { name: 'Продукты', subcategories: ['Магазин', 'Рынок'] },
    { name: 'Дом', subcategories: ['Коммунальные', 'Бытовые покупки'] },
    { name: 'Транспорт', subcategories: ['Такси', 'Общественный транспорт'] },
    { name: 'Кафе', subcategories: ['Обед', 'Кофе'] },
    { name: 'Здоровье', subcategories: ['Аптека', 'Врач'] },
    { name: 'Одежда', subcategories: [] }, { name: 'Спорт', subcategories: [] },
    { name: 'Связь', subcategories: [] }, { name: 'Подарки', subcategories: [] },
    { name: 'Другое', subcategories: [] },
  ];
  let rows: Transaction[] = [
    ['Продукты', '156.40', 'Покупки на неделю'], ['Дом', '210.00', 'Коммунальные'],
    ['Транспорт', '32.50', 'Такси'], ['Кафе', '48.00', 'Семейный обед'],
    ['Здоровье', '26.80', 'Аптека'],
  ].map(([category, amount, description], index) => ({
    transaction_id: `demo-${index}`, version: '1', date: `${month}-01`, category, amount, description,
    author_id: index % 2 ? 43 : 42, author_name: index % 2 ? 'Анна' : 'Иван',
    created_at: null, updated_at: null,
  }));
  // Twelve previous months with different spending patterns for both authors.
  for (let offset = 1; offset <= 12; offset++) {
    const date = new Date(`${month}-01T12:00:00`);
    date.setMonth(date.getMonth() - offset);
    const historicalMonth = date.toLocaleDateString('sv-SE').slice(0, 7);
    for (let index = 0; index < categories.length; index++) {
      for (const authorId of [42, 43]) {
        const seasonal = (offset * 37 + index * 19 + authorId * 11) % 130;
        const base = index === 0 ? 160 : index === 1 ? 100 : 18;
        const amount = (base + seasonal + (authorId === 43 ? offset * 3 : 12 - offset)).toFixed(2);
        rows.push({ transaction_id: `demo-${historicalMonth}-${index}-${authorId}`, version: '1',
          date: `${historicalMonth}-${String(2 + (index * 2 + authorId) % 25).padStart(2, '0')}`,
          amount, category: categories[index].name,
          description: categories[index].subcategories[0] ?? 'Плановые покупки',
          author_id: authorId, author_name: authorId === 42 ? 'Иван' : 'Анна', created_at: null, updated_at: null });
      }
    }
  }
  let reminders: ReminderResponse = { reminder_enabled: false, reminder_time: '20:00', reminder_days: [0, 1, 2, 3, 4, 5, 6], timezone: 'Europe/Minsk', chat_connected: false };
  const requests = new Map<string, Transaction>();
  const sum = (items: Transaction[]) => items.reduce((n, row) => n + Math.round(Number(row.amount) * 100), 0) / 100;
  const money = (n: number) => n.toFixed(2);
  const grouped = (items: Transaction[]) => categories.map(({ name }) => ({ category: name, amount: money(sum(items.filter(row => row.category === name))) })).filter(row => Number(row.amount) > 0);
  const participants = () => [42, 43].map(id => ({ author_id: id, author_name: id === 42 ? 'Иван' : 'Анна' }));
  const response = (value: unknown, status = 200) => new Response(status === 204 ? null : JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
  const send: typeof fetch = async (input, options) => {
    if (options?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const url = new URL(String(input), 'http://localhost');
    const path = url.pathname.slice(5);
    const query = url.searchParams;
    const method = options?.method ?? 'GET';
    const body = options?.body ? JSON.parse(String(options.body)) : undefined;
    const filtered = () => rows.filter(row =>
      (!query.get('date_from') || row.date >= query.get('date_from')!) &&
      (!query.get('date_to') || row.date <= query.get('date_to')!) &&
      (!query.get('category') || row.category === query.get('category')) &&
      (!query.get('author_id') || String(row.author_id) === query.get('author_id')) &&
      (query.get('unknown_author') !== 'true' || row.author_id === null) &&
      (!query.get('search') || `${row.description} ${row.category}`.toLowerCase().includes(query.get('search')!.toLowerCase()))
    ).sort((a, b) => b.date.localeCompare(a.date));
    if (path === 'me') return response(user);
    if (path === 'categories') return response(categories);
    if (path === 'reminders') {
      if (method === 'PUT') reminders = { ...body, chat_connected: false };
      return response(reminders);
    }
    if (path === 'home') {
      const current = rows.filter(row => row.date.startsWith(month));
      const total = sum(current), previousTotal = sum(rows.filter(row => row.date.startsWith(previousMonth)));
      return response({ month, total: money(total), previous_total: money(previousTotal), change: money(total - previousTotal), change_percent: previousTotal ? money((total / previousTotal - 1) * 100) : null, categories: grouped(current), recent: current.slice(0, 5) });
    }
    if (path === 'transactions/categories') return response(categories.map(row => row.name));
    if (path === 'transactions/participants') return response(participants());
    if (path === 'transactions') {
      if (method === 'POST') {
        if (requests.has(body.request_id)) return response(requests.get(body.request_id), 201);
        const row: Transaction = { ...body, transaction_id: crypto.randomUUID(), version: '1', author_id: 42, author_name: 'Иван', created_at: new Date().toISOString(), updated_at: null };
        rows.unshift(row); requests.set(body.request_id, row);
        return response(row, 201);
      }
      const items = filtered(), offset = Number(query.get('offset') ?? 0), limit = Number(query.get('limit') ?? 20);
      return response({ items: items.slice(offset, offset + limit), total: items.length, next_offset: offset + limit < items.length ? offset + limit : null });
    }
    if (path.startsWith('transactions/')) {
      const row = rows.find(row => row.transaction_id === decodeURIComponent(path.slice(13)));
      if (!row) return response({}, 404);
      if (method !== 'GET' && (body?.version ?? query.get('version')) !== row.version) return response({}, 409);
      if (method === 'DELETE') { rows = rows.filter(item => item !== row); return response(null, 204); }
      if (method === 'PATCH') Object.assign(row, body, { version: String(Number(row.version) + 1), updated_at: new Date().toISOString() });
      return response(row);
    }
    if (path === 'statistics') {
      const mode = query.get('mode') ?? 'months';
      let months: string[] = [];
      if (mode === 'compare') months = [query.get('compare_from') ?? previousMonth, query.get('compare_to') ?? month];
      else {
        const start = mode === 'range' ? query.get('month_from') ?? month : month;
        const end = mode === 'range' ? query.get('month_to') ?? month : month;
        const date = new Date(`${start}-01T12:00:00`);
        if (mode === 'months') date.setMonth(date.getMonth() - (Number(query.get('months') ?? 1) - 1));
        for (let i = 0; i < 120 && date.toLocaleDateString('sv-SE').slice(0, 7) <= end; i++, date.setMonth(date.getMonth() + 1)) months.push(date.toLocaleDateString('sv-SE').slice(0, 7));
      }
      const family = rows.filter(row => months.includes(row.date.slice(0, 7)));
      const selected = filtered().filter(row => months.includes(row.date.slice(0, 7)));
      const monthly = (items: Transaction[]) => months.map((m, i) => {
        const total = sum(items.filter(row => row.date.startsWith(m)));
        const before = i ? sum(items.filter(row => row.date.startsWith(months[i - 1]))) : null;
        return { month: m, total: money(total), change: before === null ? null : money(total - before), change_percent: before ? money((total / before - 1) * 100) : null };
      });
      const totals = monthly(selected);
      const data: StatisticsSummary = {
        mode, months, author_id: query.has('author_id') ? Number(query.get('author_id')) : null, unknown_author: query.get('unknown_author') === 'true',
        total: money(sum(selected)), family_total: money(sum(family)), count: selected.length, categories: grouped(selected), monthly: totals,
        available_participants: participants(), participants: participants().map(person => {
          const items = selected.filter(row => row.author_id === person.author_id);
          return { ...person, total: money(sum(items)), share_percent: sum(selected) ? money(sum(items) / sum(selected) * 100) : null, count: items.length, average: money(items.length ? sum(items) / items.length : 0), categories: grouped(items), monthly: monthly(items) };
        }),
        comparison: mode === 'compare' ? { month_from: months[0], month_to: months[1], from_total: totals[0].total, to_total: totals[1].total, change: money(Number(totals[1].total) - Number(totals[0].total)), change_percent: Number(totals[0].total) ? money((Number(totals[1].total) / Number(totals[0].total) - 1) * 100) : null } : null,
      };
      return response(data);
    }
    return response({}, 404);
  };
  return new ApiClient(() => ({ initData: '', development: true, devAuthEnabled: true, devUserId: '42', hostname: 'localhost' }), send);
}
