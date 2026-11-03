import { FormEvent, useEffect, useRef, useState } from 'react';
import { ApiClient, ApiError, Category, CurrentUser, Participant, Transaction, TransactionFilters, TransactionPage, Trip, ExpenseScope } from '../api';
import { validDate } from './Home';
import { PullToRefresh } from './PullToRefresh';
import { FinanceIcon, categoryIcon } from './FinanceIcon';
import { StatusScreen } from './StatusScreen';

const money = (value: string) => `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} BYN`;
const emptyFilters = { from: '', to: '', category: '', author: '', search: '', scope: 'all' as ExpenseScope, trip: '' };

function recentMonthFilters() {
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 29);
  const date = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
  return { ...emptyFilters, from: date(start), to: date(today) };
}

export function Transactions({ client, user, onDenied, onChanged }: {
  client: ApiClient; user: CurrentUser; onDenied: () => void; onChanged: () => void;
}) {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [travelCategories, setTravelCategories] = useState<Category[]>([]);
  const [currencies, setCurrencies] = useState(['BYN', 'EUR', 'USD']);
  const [categories, setCategories] = useState<Category[]>([]);
  const [ledgerCategories, setLedgerCategories] = useState<string[]>([]);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [optionsError, setOptionsError] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [draft, setDraft] = useState(recentMonthFilters);
  const [filters, setFilters] = useState<TransactionFilters>(() => ({ date_from: draft.from, date_to: draft.to }));
  const [page, setPage] = useState<TransactionPage | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Transaction | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [form, setForm] = useState({ date: '', amount: '', category: '', description: '', currency: 'BYN', trip_id: null as string | null });
  const [operationError, setOperationError] = useState('');
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const editor = useRef<HTMLElement>(null);
  const amountInput = useRef<HTMLInputElement>(null);
  const lock = useRef(false);
  const generation = useRef(0);
  const deny = useRef(onDenied); deny.current = onDenied;
  const refreshHome = useRef(onChanged); refreshHome.current = onChanged;

  useEffect(() => {
    if (!selected) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    (amountInput.current && !amountInput.current.disabled ? amountInput.current : editor.current?.querySelector<HTMLButtonElement>('button:not(:disabled)'))?.focus();
    return () => { document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus(); };
  }, [!!selected]);

  useEffect(() => {
    const controller = new AbortController();
    const version = ++generation.current;
    setLoading(true); setError(''); setPage(null);
    client.transactions(filters, controller.signal).then((result) => {
      if (!controller.signal.aborted && version === generation.current) setPage(result);
    }).catch((err) => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setError('Не удалось загрузить транзакции.');
    }).finally(() => { if (!controller.signal.aborted && version === generation.current) setLoading(false); });
    return () => controller.abort();
  }, [client, filters, attempt]);

  useEffect(() => {
    const controller = new AbortController();
    setOptionsError('');
    Promise.all([client.categories(controller.signal), client.participants(controller.signal), client.transactionCategories(controller.signal)]).then(([cats, people, names]) => {
      if (!controller.signal.aborted) { setCategories(cats); setParticipants(people); setLedgerCategories(names); }
    }).catch((err) => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setOptionsError('Не удалось загрузить варианты фильтров. Повторите загрузку.');
    });
    return () => controller.abort();
  }, [client, attempt]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([client.trips(controller.signal), client.categories(controller.signal, true), client.travelContext(controller.signal)]).then(([items, cats, context]) => {
      if (!controller.signal.aborted) { setTrips(items); setTravelCategories(cats); setCurrencies(context.currencies); }
    }).catch(err => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setOptionsError('Не удалось загрузить поездки и валюты. Повторите загрузку.');
    });
    return () => controller.abort();
  }, [client, attempt]);

  function apply(event: FormEvent) {
    event.preventDefault();
    if ((draft.from && !validDate(draft.from)) || (draft.to && !validDate(draft.to)) || (draft.from && draft.to && draft.from > draft.to)) {
      setError('Укажите корректный период: начало не позже окончания.'); return;
    }
    setFiltersOpen(false); setSelected(null); setNotice('');
    setFilters({ ...(draft.scope !== 'all' ? { scope: draft.scope } : {}), ...(draft.trip ? { trip_id: draft.trip } : {}), ...(draft.from ? { date_from: draft.from } : {}), ...(draft.to ? { date_to: draft.to } : {}),
      ...(draft.category ? { category: draft.category } : {}), ...(draft.author === 'unknown' ? { unknown_author: 'true' }
        : draft.author ? { author_id: draft.author } : {}), ...(draft.search.trim() ? { search: draft.search.trim() } : {}) });
  }

  async function more() {
    if (lock.current || page?.next_offset == null) return;
    const version = generation.current;
    lock.current = true; setLoading(true); setError('');
    try {
      const next = await client.transactions({ ...filters, offset: String(page.next_offset) });
      if (version === generation.current) setPage({ ...next, items: [...page.items, ...next.items] });
    } catch (err) {
      if (version !== generation.current) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setError('Не удалось загрузить следующую страницу.');
    } finally { lock.current = false; if (version === generation.current) setLoading(false); }
  }

  function choose(item: Transaction) {
    setSelected(item); setConfirmDelete(false); setOperationError(''); setStale(false); setNotice('');
    setForm({ date: item.date, amount: item.original_amount ?? item.amount, category: item.category, description: item.description, currency: item.currency ?? 'BYN', trip_id: item.trip_id ?? null });
  }

  async function reloadSelected() {
    if (lock.current || !selected?.transaction_id) return;
    lock.current = true; setBusy(true);
    try {
      choose(await client.transaction(selected.transaction_id));
      refreshHome.current(); setAttempt((n) => n + 1);
    } catch (err) {
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else if (err instanceof ApiError && err.status === 404) {
        setSelected(null); setNotice('Операция уже удалена.'); refreshHome.current(); setAttempt((n) => n + 1);
      } else setOperationError('Не удалось обновить операцию. Введённые данные сохранены.');
    } finally { lock.current = false; setBusy(false); }
  }

  async function mutate(kind: 'edit' | 'delete', event?: FormEvent) {
    event?.preventDefault();
    if (lock.current || stale || !selected?.transaction_id || !selected.version
        || !(user.role === 'admin' || selected.author_id === user.telegram_user_id)) return;
    const amount = form.amount.trim().replace(',', '.');
    if (kind === 'edit' && (!validDate(form.date) || !/^\d{1,10}(?:\.\d{1,2})?$/.test(amount) || Number(amount) <= 0
      || (!expenseCategories.some((c) => c.name === form.category) && form.category !== selected.category))) {
      setOperationError('Проверьте положительную сумму, категорию и дату.'); return;
    }
    lock.current = true; setBusy(true); setOperationError('');
    try {
      if (kind === 'edit') await client.updateTransaction(selected.transaction_id, { ...form, amount, description: form.description.trim(), version: selected.version });
      else await client.deleteTransaction(selected.transaction_id, selected.version);
      setSelected(null); setNotice(kind === 'edit' ? 'Операция изменена.' : 'Операция удалена.');
      refreshHome.current(); setAttempt((n) => n + 1);
    } catch (err) {
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else {
        // Ambiguous failures may follow a successful write: require an explicit
        // refresh before another mutation, preserving the user's draft meanwhile.
        setStale(!(err instanceof ApiError && err.status === 422));
        setOperationError(err instanceof ApiError ? err.message : 'Не удалось подтвердить результат. Обновите операцию.');
        if (!(err instanceof ApiError && err.status === 422)) refreshHome.current();
      }
    } finally { lock.current = false; setBusy(false); }
  }

  const canManage = !!selected?.transaction_id && !!selected.version && (user.role === 'admin' || selected.author_id === user.telegram_user_id);
  const expenseCategories = form.trip_id ? travelCategories : categories;
  const selectedCategory = expenseCategories.find((c) => c.name === form.category);
  const filterCategories = Array.from(new Set([...ledgerCategories, ...categories.map((c) => c.name), ...(page?.items.map((t) => t.category) ?? []), draft.category].filter(Boolean)));
  function refreshList() {
    if (lock.current || busy || loading || selected) return;
    setAttempt(n => n + 1);
  }
  return <PullToRefresh disabled={busy || loading || !!selected} onRefresh={refreshList}><div className="transactions">
    <div className="transaction-background" inert={!!selected}>
    <div className="filter-toolbar"><button className="secondary-button filter-toggle" type="button" aria-expanded={filtersOpen} aria-controls="transaction-filters" onClick={() => setFiltersOpen(open => !open)}>Фильтры{Object.keys(filters).length > 0 ? ` · ${Object.keys(filters).length}` : ''}</button></div>
    <section id="transaction-filters" hidden={!filtersOpen} className="home-card" aria-label="Фильтры транзакций">
      <form onSubmit={apply}>
        <fieldset disabled={busy || loading}>
          <label>Тип расходов<select value={draft.scope} onChange={e => setDraft({ ...draft, scope: e.target.value as ExpenseScope })}><option value="all">Все расходы</option><option value="everyday">Обычная жизнь</option><option value="travel">Поездки</option></select></label>
          <label>Поездка фильтра<select value={draft.trip} onChange={e => setDraft({ ...draft, trip: e.target.value, scope: e.target.value ? 'travel' : draft.scope })}><option value="">Все поездки</option>{trips.map(t => <option value={t.trip_id} key={t.trip_id}>{t.name}</option>)}</select></label>
          <label>Период с<input type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} /></label>
          <label>Период по<input type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} /></label>
          <label>Категория фильтра<select value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })}><option value="">Все категории</option>{filterCategories.map((c) => <option key={c}>{c}</option>)}</select></label>
          <label>Участник<select value={draft.author} onChange={(e) => setDraft({ ...draft, author: e.target.value })}><option value="">Вся семья</option>{participants.map((p) => <option key={p.author_id ?? 'unknown'} value={p.author_id ?? 'unknown'}>{p.author_name}</option>)}</select></label>
          <label>Поиск по описанию<input type="search" maxLength={500} value={draft.search} onChange={(e) => setDraft({ ...draft, search: e.target.value })} /></label>
        </fieldset>
        <button className="primary-button" disabled={busy || loading}>Применить фильтры</button>
        <button className="secondary-button" type="button" disabled={busy || loading} onClick={() => { setDraft(emptyFilters); setFilters({}); setSelected(null); }}>Сбросить</button>
      </form>
      {optionsError && <p role="alert">{optionsError}</p>}
    </section>
    {notice && <p role="status">{notice}</p>}
    {error && <StatusScreen kind="error" title={error} onRetry={() => setAttempt((n) => n + 1)} />}
    {loading && <p role="status">Загружаем транзакции…</p>}
    {page && <section className="home-card" aria-label="Список транзакций">
      <h2>Найдено операций: {page.total}</h2>
      {!page.items.length ? <p>По выбранным условиям операций нет.</p> : <ul className="recent-list">
        {page.items.map((item, index) => <li key={item.transaction_id ?? `legacy-${index}`}>
          <button className="transaction-button" disabled={busy} onClick={() => choose(item)}><strong>{item.category} · {money(item.amount)}</strong><span>{item.description || 'Без описания'}</span><span>{item.currency && item.currency !== 'BYN' ? `${item.original_amount} ${item.currency} · ` : ''}{trips.find(t => t.trip_id === item.trip_id)?.name}</span><span className="transaction-meta">{item.date.split('-').reverse().join('.')} · {item.author_name}</span></button>
        </li>)}
      </ul>}
      {page.next_offset !== null && <button className="secondary-button" disabled={loading || busy} onClick={() => void more()}>Загрузить ещё</button>}
    </section>}
    </div>
    {selected && <section className="expense-editor transaction-editor" ref={editor} role="dialog" aria-modal="true" aria-labelledby="transaction-editor-title" onKeyDown={event => {
      if (event.key === 'Escape' && !busy) { event.preventDefault(); setSelected(null); }
      if (event.key === 'Tab') {
        const nodes = editor.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)');
        if (!nodes?.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }}>
      <header className="editor-header"><button type="button" disabled={busy} onClick={() => setSelected(null)}>Закрыть операцию</button><h2 id="transaction-editor-title">{canManage ? 'Редактировать расход' : 'Просмотр расхода'}</h2><FinanceIcon name={categoryIcon(form.category)} /></header>
      <form onSubmit={event => void mutate('edit', event)} noValidate>
        <p className="transaction-meta">{selected.author_name} · {selected.date.split('-').reverse().join('.')}</p>
        <fieldset disabled={busy || stale || !canManage}>
          <label>Поездка операции<select value={form.trip_id ?? ''} onChange={e => setForm({ ...form, trip_id: e.target.value || null, category: '' })}><option value="">Обычный расход</option>{trips.map(t => <option value={t.trip_id} key={t.trip_id}>{t.name}</option>)}</select></label>
          <label>Валюта операции<select value={form.currency} onChange={e => setForm({ ...form, currency: e.target.value })}>{currencies.map(c => <option key={c}>{c}</option>)}</select></label>
          <label className="editor-date">Дата операции<input type="date" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} /></label>
          <label className="amount-field">Сумма операции, {form.currency}<input ref={amountInput} inputMode="none" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} /></label>
          <label className={selectedCategory?.subcategories.length ? undefined : 'editor-category-wide'}>Категория операции<select value={form.category} onChange={e => setForm({ ...form, category: e.target.value, description: '' })}>{!expenseCategories.some(c => c.name === selected.category) && <option>{selected.category}</option>}{expenseCategories.map(c => <option key={c.name}>{c.name}</option>)}</select></label>
          {!!selectedCategory?.subcategories.length && <label>Подкатегория операции<select value={selectedCategory.subcategories.includes(form.description) ? form.description : ''} onChange={e => setForm({ ...form, description: e.target.value })}><option value="">Не выбрана</option>{selectedCategory.subcategories.map(s => <option key={s}>{s}</option>)}</select></label>}
          <label className="editor-note">Описание операции<input maxLength={500} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} placeholder="Добавить заметку" /></label>
        </fieldset>
        {canManage && <>
          <div className="numeric-keypad" aria-label="Цифровая клавиатура">{['1', '2', '3', '4', '5', '6', '7', '8', '9', ',', '0', '⌫'].map(key => <button type="button" key={key} disabled={busy || stale} aria-label={key === '⌫' ? 'Удалить последнюю цифру' : key === ',' ? 'Десятичная запятая' : key} onClick={() => setForm(value => {
            const next = key === '⌫' ? value.amount.slice(0, -1) : value.amount === '0' && key !== ',' ? key : value.amount + key;
            return /^\d{0,10}(?:[.,]\d{0,2})?$/.test(next) ? { ...value, amount: next } : value;
          })}>{key}</button>)}</div>
          <button className="clear-amount" type="button" disabled={busy || stale} onClick={() => setForm({ ...form, amount: '' })}>Очистить сумму</button>
          <button className="primary-button" disabled={busy || stale}>Сохранить изменения</button>
          {!confirmDelete && <button className="danger-button" type="button" disabled={busy || stale} onClick={() => setConfirmDelete(true)}>Удалить</button>}
        </>}
        {confirmDelete && <div role="group" aria-label="Подтверждение удаления"><p>Удалить эту операцию? Отменить удаление нельзя.</p>
          <button className="danger-button" type="button" disabled={busy || stale} onClick={() => void mutate('delete')}>Подтвердить удаление</button>
          <button className="secondary-button" type="button" disabled={busy} onClick={() => setConfirmDelete(false)}>Отмена удаления</button>
        </div>}
        {!canManage && <p>{!selected.transaction_id ? 'Для изменения требуется миграция постоянных ID.' : 'Изменять эту операцию может её автор или администратор.'}</p>}
        {operationError && <p role="alert">{operationError}</p>}
        {stale && <><p>Введённые данные сохранены в форме. Загрузка актуальной операции заменит их данными таблицы.</p><button className="secondary-button" type="button" disabled={busy} onClick={() => void reloadSelected()}>Загрузить актуальную операцию</button></>}
      </form>
    </section>}

  </div></PullToRefresh>;
}
