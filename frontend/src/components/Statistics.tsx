import { FormEvent, useEffect, useRef, useState } from 'react';
import { ApiClient, ApiError, MonthTotal, Participant, StatisticsQuery, StatisticsSummary } from '../api';
import { todayInMinsk } from './Home';
import { ParticipantMonthlyChart } from './ParticipantMonthlyChart';
import { StatusScreen } from './StatusScreen';

const money = (value: string) => `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} BYN`;
const percent = (value: string | null) => value === null ? 'не определён' : `${Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} %`;
const validMonth = (value: string) => /^\d{4}-(0[1-9]|1[0-2])$/.test(value) && !value.startsWith('0000');

function Bars({ label, items }: { label: string; items: { label: string; amount: string }[] }) {
  const maximum = Math.max(0, ...items.map((item) => Number(item.amount)));
  return <ul className="category-chart" aria-label={label}>
    {items.map((item) => <li key={item.label}>
      <div><span>{item.label}</span><strong>{money(item.amount)}</strong></div>
      <div className="bar-track" aria-hidden="true"><div className="bar" style={{ width: `${maximum ? Math.max(0, Number(item.amount) / maximum * 100) : 0}%` }} /></div>
    </li>)}
  </ul>;
}

function Dynamics({ items, label }: { items: MonthTotal[]; label: string }) {
  return <><Bars label={label} items={items.map((item) => ({ label: item.month, amount: item.total }))} />

  </>;
}

export function Statistics({ client, onDenied }: { client: ApiClient; onDenied: () => void }) {
  const current = todayInMinsk().slice(0, 7);
  const previousDate = new Date(`${current}-01T00:00:00Z`);
  previousDate.setUTCMonth(previousDate.getUTCMonth() - 1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [period, setPeriod] = useState('6');
  const [monthFrom, setMonthFrom] = useState(current);
  const [monthTo, setMonthTo] = useState(current);
  const [compareFrom, setCompareFrom] = useState(previousDate.toISOString().slice(0, 7));
  const [compareTo, setCompareTo] = useState(current);
  const [author, setAuthor] = useState('');
  const [query, setQuery] = useState<StatisticsQuery>({ mode: 'months', months: '6' });
  const [data, setData] = useState<StatisticsSummary | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [error, setError] = useState('');
  const [validation, setValidation] = useState('');
  const [attempt, setAttempt] = useState(0);
  const deny = useRef(onDenied); deny.current = onDenied;

  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError('');
    client.statistics(query, controller.signal).then((result) => {
      if (!controller.signal.aborted) { setData(result); setParticipants(result.available_participants); }
    }).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setError(err instanceof ApiError ? err.message : 'Не удалось загрузить статистику.');
    });
    return () => controller.abort();
  }, [client, query, attempt]);

  function apply(event: FormEvent) {
    event.preventDefault(); setValidation('');
    let next: StatisticsQuery;
    if (period === 'range') {
      if (!validMonth(monthFrom) || !validMonth(monthTo) || monthFrom > monthTo) {
        setValidation('Укажите диапазон месяцев: начало должно быть не позже окончания.'); return;
      }
      next = { mode: 'range', month_from: monthFrom, month_to: monthTo };
    } else if (period === 'compare') {
      if (!validMonth(compareFrom) || !validMonth(compareTo) || compareFrom === compareTo) {
        setValidation('Выберите два разных месяца для сравнения.'); return;
      }
      next = { mode: 'compare', compare_from: compareFrom, compare_to: compareTo };
    } else next = { mode: 'months', months: period };
    if (author === 'unknown') next.unknown_author = 'true';
    else if (author) next.author_id = author;
    setQuery(next); setFiltersOpen(false);
  }

  return <div className="statistics">
    <div className="filter-toolbar"><button className="secondary-button filter-toggle" type="button" aria-expanded={filtersOpen} aria-controls="statistics-filters" onClick={() => setFiltersOpen(open => !open)}>Фильтры</button></div>
    <section id="statistics-filters" hidden={!filtersOpen} className="home-card" aria-labelledby="statistics-filter-title">
      <h2 id="statistics-filter-title">Период и участник</h2>
      <form onSubmit={apply} noValidate>
        <fieldset>
          <label>Период статистики<select value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="1">Текущий месяц</option>
            {[2, 3, 6, 12].map((n) => <option key={n} value={n}>Последние {n} месяцев</option>)}
            <option value="range">Диапазон месяцев</option><option value="compare">Сравнение двух месяцев</option>
          </select></label>
          {period === 'range' && <>
            <label>Начальный месяц<input type="month" value={monthFrom} onChange={(e) => setMonthFrom(e.target.value)} /></label>
            <label>Конечный месяц<input type="month" value={monthTo} onChange={(e) => setMonthTo(e.target.value)} /></label>
          </>}
          {period === 'compare' && <>
            <label>Базовый месяц<input type="month" value={compareFrom} onChange={(e) => setCompareFrom(e.target.value)} /></label>
            <label>Сравниваемый месяц<input type="month" value={compareTo} onChange={(e) => setCompareTo(e.target.value)} /></label>
          </>}
          <label>Участник статистики<select value={author} onChange={(e) => setAuthor(e.target.value)}>
            <option value="">Вся семья</option>
            {participants.map((item) => <option key={item.author_id ?? 'unknown'} value={item.author_id ?? 'unknown'}>{item.author_name}</option>)}
          </select></label>
        </fieldset>
        {validation && <p role="alert" className="form-error">{validation}</p>}
        <button className="primary-button" type="submit">Показать статистику</button>
      </form>
    </section>
    {error ? <StatusScreen kind="error" title={error} onRetry={() => setAttempt((n) => n + 1)} />
      : !data ? <StatusScreen kind="loading" title="Загружаем статистику" /> : <>
        {data.count === 0 && <p role="status">За выбранный период расходов нет.</p>}
        {data.comparison && <section className="home-card" aria-labelledby="month-comparison-title">
          <h2 id="month-comparison-title">Сравнение месяцев</h2>
          <p>{data.comparison.month_from}: {money(data.comparison.from_total)}</p>
          <p>{data.comparison.month_to}: {money(data.comparison.to_total)}</p>
          <p>Разница: {money(data.comparison.change)}</p>
          <p>Изменение: {percent(data.comparison.change_percent)}</p>
        </section>}
        <ParticipantMonthlyChart months={data.months} participants={data.participants} monthly={data.monthly} />
        <section className="home-card" aria-labelledby="statistics-categories-title">
          <h2 id="statistics-categories-title">Расходы по категориям</h2>
          {data.categories.length ? <Bars label="Диаграмма категорий" items={data.categories.map((item) => ({ label: item.category, amount: item.amount }))} /> : <p>Нет расходов по категориям.</p>}
        </section>
        <section className="home-card" aria-labelledby="participant-comparison-title">
          <h2 id="participant-comparison-title">Сравнение участников — вся семья</h2>
          <p>Показатели участников рассчитаны за выбранные месяцы; доля — от общей суммы семьи, включая расходы без автора.</p>
          {data.participants.length ? <>
            <Bars label="Диаграмма сравнения участников" items={data.participants.map((item) => ({ label: `${item.author_name}${item.author_id === null ? '' : ` · ${item.author_id}`}`, amount: item.total }))} />
            {data.participants.map((item) => <details className="participant-statistics" key={item.author_id ?? 'unknown'}>
              <summary>{item.author_name} · {money(item.total)} · доля: {percent(item.share_percent)}</summary>
              <p>Количество операций: {item.count}</p><p>Средняя сумма: {money(item.average)}</p>
              <h3>Категории участника</h3>
              {item.categories.length ? <Bars label={`Категории: ${item.author_name}`} items={item.categories.map((c) => ({ label: c.category, amount: c.amount }))} /> : <p>Нет расходов по категориям.</p>}
              <h3>Динамика участника</h3><Dynamics label={`Динамика: ${item.author_name}`} items={item.monthly} />
            </details>)}
          </> : <p>В книге пока нет участников с расходами.</p>}
        </section>
      </>}
  </div>;
}
