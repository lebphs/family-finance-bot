import { FormEvent, useEffect, useRef, useState } from 'react';
import { ApiClient, ApiError, Category, ExpenseInput, HomeSummary, Trip } from '../api';
import { StatusScreen } from './StatusScreen';
import { ExpenseWheel } from './ExpenseWheel';
import { categoryIcon, FinanceIcon } from './FinanceIcon';

export function todayInMinsk(): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Minsk', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}
export function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function Home({ refresh = 0, client, onDenied, requestedTrip, onTripConsumed }: { refresh?: number; client: ApiClient; onDenied: () => void; onTransactions: () => void; requestedTrip?: Trip | null; onTripConsumed?: () => void }) {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [tripId, setTripId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [currency, setCurrency] = useState('BYN');
  const [currencies, setCurrencies] = useState<string[]>(['BYN', 'EUR', 'USD']);
  const [contextReady, setContextReady] = useState(false);
  const [contextError, setContextError] = useState('');
  const [contextAttempt, setContextAttempt] = useState(0);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoriesReady, setCategoriesReady] = useState(false);
  const [categoryError, setCategoryError] = useState('');
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [summaryError, setSummaryError] = useState('');
  const [amount, setAmount] = useState('');
  const [category, setCategory] = useState('');
  const [description, setDescription] = useState('');
  const [date, setDate] = useState(todayInMinsk);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const editor = useRef<HTMLElement>(null);
  const amountInput = useRef<HTMLInputElement>(null);
  const busy = useRef(false);
  const explicitTrip = useRef(false);
  const lastActiveId = useRef<string | null>(null);
  useEffect(() => {
    if (!formOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    amountInput.current?.focus();
    return () => { document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus(); };
  }, [formOpen]);
  function selectTrip(identifier: string | null) {
    explicitTrip.current = true;
    setTripId(identifier); setCurrency(trips.find(t => t.trip_id === identifier)?.currency ?? 'BYN');
    setCategory(''); setDescription(''); setCategoriesReady(false);
  }
  function openExpense(name = category) {
    if (name !== category) { setCategory(name); setDescription(''); }
    if (!uncertain) { setSuccess(''); setError(''); }
    setFormOpen(true);
  }
  function keypad(key: string) {
    if (saving || uncertain) return;
    setAmount((value) => {
      if (key === '⌫') return value.slice(0, -1);
      if (key === 'C') return '';
      const next = key === ',' && !value ? '0,' : value + key;
      return /^\d{0,10}(?:[.,]\d{0,2})?$/.test(next) ? next : value;
    });
  }

  const summaryVersion = useRef(0);
  // A failed/ambiguous response retains both payload and key for a safe retry.
  const pending = useRef<ExpenseInput | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const deny = useRef(onDenied);
  deny.current = onDenied;

  useEffect(() => {
    const controller = new AbortController();
    setContextError('');
    Promise.all([client.trips(controller.signal), client.travelContext(controller.signal)]).then(([items, context]) => {
      if (controller.signal.aborted) return;
      const nextActive = context.trip?.trip_id ?? null;
      if (nextActive !== lastActiveId.current && !pending.current && !requestedTrip) explicitTrip.current = false;
      lastActiveId.current = nextActive;
      setTrips(items); setCurrencies(context.currencies); setActiveId(nextActive);
      if (!pending.current && !explicitTrip.current && !requestedTrip) {
        setTripId(context.trip?.trip_id ?? null); setCurrency(context.trip?.currency ?? 'BYN'); setCategory('');
      }
      setContextReady(true);
    }).catch(err => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setContextError('Не удалось загрузить режим поездки. Повторите загрузку перед сохранением.');
    });
    return () => controller.abort();
  }, [client, refresh, contextAttempt]);

  useEffect(() => {
    if (!requestedTrip) return;
    if (pending.current) { setError('Сначала завершите сохранение текущего расхода.'); onTripConsumed?.(); return; }
    explicitTrip.current = true;
    setTripId(requestedTrip.trip_id); setCurrency(requestedTrip.currency); setCategory(''); setDescription('');
    setFormOpen(true); onTripConsumed?.();
  }, [requestedTrip]);

  useEffect(() => {
    const controller = new AbortController();
    const version = ++summaryVersion.current;
    setCategoryError(''); setSummaryError('');
    setCategoriesReady(false);
    client.categories(controller.signal, !!tripId).then((items) => {
      if (!controller.signal.aborted) { setCategories(items); setCategoriesReady(true); }
    }).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setCategoryError('Не удалось загрузить категории.');
    });
    client.home(controller.signal).then((data) => {
      if (!controller.signal.aborted && version === summaryVersion.current) setSummary(data);
    }).catch((err: unknown) => {
      if (controller.signal.aborted || version !== summaryVersion.current) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setSummaryError('Не удалось загрузить сводку.');
    });
    return () => controller.abort();
  }, [client, attempt, refresh, tripId]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy.current) return;
    const normalized = amount.trim().replace(',', '.');
    if (!pending.current) {
      if (!/^\d{1,10}(?:\.\d{1,2})?$/.test(normalized) || Number(normalized) <= 0) {
        setError('Введите положительную сумму, не более двух знаков после запятой.'); return;
      }
      if (!categories.some((item) => item.name === category)) { setError('Выберите категорию из списка.'); return; }
      if (!validDate(date)) { setError('Укажите дату в формате ГГГГ-ММ-ДД.'); return; }
      if (!contextReady || contextError) { setError('Сначала загрузите режим поездки.'); return; }
      pending.current = { request_id: crypto.randomUUID(), amount: normalized, category, description: description.trim(), date,
        trip_id: tripId, currency };
    }
    busy.current = true; setSaving(true); setError(''); setSuccess('');
    try {
      await client.createExpense(pending.current);
      pending.current = null; setUncertain(false);
      setAmount(''); setDescription(''); setDate(todayInMinsk());
      // One-off overrides must not leak into the next everyday purchase.
      explicitTrip.current = false;
      if (tripId !== activeId) { setCategory(''); setCategoriesReady(false); }
      setTripId(activeId); setCurrency(trips.find(t => t.trip_id === activeId)?.currency ?? 'BYN');
      setSuccess('Расход сохранён.'); setFormOpen(false);
      // Read failure must never turn a successful write into a failed save.
      setSummary(null); setSummaryError('');
      const version = ++summaryVersion.current;
      try {
        const data = await client.home();
        if (version === summaryVersion.current) setSummary(data);
      }
      catch (err) {
        if (version !== summaryVersion.current) return;
        if (err instanceof ApiError && err.accessDenied) deny.current();
        else setSummaryError('Расход сохранён, но сводку не удалось обновить.');
      }
    } catch (err) {
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else {
        const definitive = err instanceof ApiError && (err.status === 422 || err.status === 409);
        if (definitive) { pending.current = null; setUncertain(false); }
        else setUncertain(true);
        setError(err instanceof ApiError ? err.message : 'Не удалось подтвердить сохранение. Повторите отправку.');
      }
    } finally { busy.current = false; setSaving(false); }
  }

  const selected = categories.find((item) => item.name === category);
  return <div className="home">
    <section className="home-card" inert={formOpen} aria-label="Режим расходов">
      <p>{tripId ? `Поездка: ${trips.find(t => t.trip_id === tripId)?.name ?? requestedTrip?.name ?? ''} · ${currency}` : 'Обычные расходы · BYN'}</p>
      <label>Расходы для<select disabled={saving || uncertain || !contextReady} value={tripId ?? ''} onChange={e => selectTrip(e.target.value || null)}>
        <option value="">Обычная жизнь</option>{trips.map(t => <option value={t.trip_id} key={t.trip_id}>{t.name}{t.completed ? ' · завершена' : ''}</option>)}
      </select></label>
      {activeId && !tripId && <button className="secondary-button" onClick={() => selectTrip(activeId)}>Вернуться к активной поездке</button>}
      {contextError && <p role="alert">{contextError}<button onClick={() => setContextAttempt(n => n + 1)}>Повторить загрузку режима</button></p>}
    </section>
    <section className="overview" aria-labelledby="overview-title" inert={formOpen}>
      <div className="month-heading"><span aria-hidden="true">—</span><h2 id="overview-title">{summary ? new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${summary.month}-01T00:00:00Z`)) : 'Текущий месяц'}</h2><span aria-hidden="true">—</span></div>
      <p className="overview-hint">Нажмите на категорию, чтобы добавить расход</p>
      <ExpenseWheel categories={categories} summary={summary} disabled={saving || uncertain || !contextReady || !!contextError || !categoriesReady} onCategory={openExpense} />
      {uncertain && <button className="secondary-button" onClick={() => openExpense()}>Продолжить сохранение</button>}
      {success && <p className="save-success" role="status">{success}</p>}

      {summaryError && <StatusScreen kind="error" title={summaryError} onRetry={() => setAttempt((n) => n + 1)} />}
      {categoryError && <StatusScreen kind="error" title={categoryError} onRetry={() => setAttempt((n) => n + 1)} />}
      {!categoriesReady && !categoryError && <p role="status">Загружаем категории…</p>}
      {categoriesReady && categories.length === 0 && <p>Категории пока не настроены в таблице.</p>}
    </section>
    {formOpen && <section className="expense-editor" ref={editor} role="dialog" aria-modal="true" aria-labelledby="expense-title" onKeyDown={(event) => {
      if (event.key === 'Escape' && !saving) { event.preventDefault(); setFormOpen(false); }
      if (event.key === 'Tab') {
        const nodes = editor.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)');
        if (!nodes?.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }}>
      <header className="editor-header"><button type="button" disabled={saving} onClick={() => setFormOpen(false)}>Отменить</button><h2 id="expense-title">Новый расход</h2><FinanceIcon name={categoryIcon(category)} /></header>
      <form onSubmit={submit} noValidate>
        <fieldset disabled={saving || uncertain}>
          <label>Поездка расхода<select value={tripId ?? ''} onChange={e => selectTrip(e.target.value || null)}><option value="">Обычный расход</option>{trips.map(t => <option value={t.trip_id} key={t.trip_id}>{t.name}</option>)}</select></label>
          <label>Валюта расхода<select value={currency} onChange={e => setCurrency(e.target.value)}>{currencies.map(c => <option key={c}>{c}</option>)}</select></label>
          <label className="amount-field">Сумма, {currency}<input ref={amountInput} inputMode="none" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0,00" required /></label>
          <label className={selected?.subcategories.length ? undefined : "editor-category-wide"}>Категория<select aria-label="Категория" value={category} onChange={(e) => { setCategory(e.target.value); setDescription(''); }} required>
            <option value="">Выберите категорию</option>
            {categories.map((item) => <option key={item.name}>{item.name}</option>)}
          </select></label>
          {!!selected?.subcategories.length && <label>Подкатегория<select aria-label="Подкатегория" value={selected.subcategories.includes(description) ? description : ''} onChange={(e) => setDescription(e.target.value)}>
            <option value="">Не выбрана</option>{selected.subcategories.map((name) => <option key={name}>{name}</option>)}
          </select></label>}
          <label className="editor-note">Описание или подкатегория<input value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} placeholder="Добавить заметку" /></label>
          <label className="editor-date">Дата<input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
        </fieldset>
        {error && <p className="form-error" role="alert">{error}</p>}
        {uncertain && <p>Данные сохранены в форме. Повторная отправка проверит результат и не создаст дубликат.</p>}

        <div className="numeric-keypad" aria-label="Цифровая клавиатура">{['1', '2', '3', '4', '5', '6', '7', '8', '9', ',', '0', '⌫'].map((key) => <button type="button" key={key} disabled={saving || uncertain} aria-label={key === '⌫' ? 'Удалить последнюю цифру' : key === ',' ? 'Десятичная запятая' : key} onClick={() => keypad(key)}>{key}</button>)}</div>
        <button className="clear-amount" type="button" disabled={saving || uncertain} onClick={() => keypad('C')}>Очистить сумму</button>
        <button className="primary-button" disabled={saving || (!uncertain && (!categoriesReady || !contextReady || !!contextError || categories.length === 0))} type="submit">{saving ? 'Сохраняем…' : uncertain ? 'Повторить сохранение' : 'Сохранить расход'}</button>
      </form>
    </section>}

  </div>;
}
