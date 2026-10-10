import { Category, HomeSummary } from '../api';
import { categoryColors, categoryIcon, FinanceIcon } from './FinanceIcon';
const money = (value: string) => Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const colorAt = (index: number) => categoryColors[index] ?? `hsl(${Math.round(index * 137.508) % 360} 55% 72%)`;
export function ExpenseWheel({ categories, summary, onCategory, disabled }: { categories: Category[]; summary: HomeSummary | null; onCategory: (name: string) => void; disabled: boolean }) {
  const total = Number(summary?.total ?? 0);
  const names = [...new Set([...categories.map(item => item.name), ...(summary?.categories.map(item => item.category) ?? [])])];
  const color = (name: string) => colorAt(names.indexOf(name));
  let offset = 0;
  const segments = (summary?.categories ?? []).filter(item => Number(item.amount) > 0).map(item => {
    const share = total > 0 ? Math.max(0, Math.min(1, Number(item.amount) / total)) : 0;
    const start = offset; offset += share;
    return { ...item, share, start, color: color(item.category) };
  });
  return <>
    <div className={`expense-wheel${categories.length > 12 ? ' expense-wheel-dense' : ''}`}>
      <svg className="donut" viewBox="0 0 200 200" aria-hidden="true">
        <circle cx="100" cy="100" r="78" fill="none" stroke="var(--ring-empty)" strokeWidth="35" />
        {segments.map(segment => <circle key={segment.category} cx="100" cy="100" r="78" fill="none" stroke={segment.color} strokeWidth="35" pathLength="1" strokeDasharray={`${segment.share} ${1 - segment.share}`} strokeDashoffset={-segment.start} transform="rotate(-90 100 100)" />)}
        {segments.filter(segment => segment.share >= .07).map(segment => {
          const angle = (-.25 + segment.start + segment.share / 2) * 2 * Math.PI;
          return <text className="donut-share" key={segment.category} x={100 + 78 * Math.cos(angle)} y={100 + 78 * Math.sin(angle)} textAnchor="middle" dominantBaseline="middle">{Math.round(segment.share * 100)}%</text>;
        })}
      </svg>
      <div className="donut-total"><span>Расходы за месяц</span><strong>{summary ? money(summary.total) : '…'}</strong><span>BYN</span></div>
      {categories.map((item, index) => {
        const angle = (-90 + index * 360 / Math.max(categories.length, 6)) * Math.PI / 180;
        const share = total > 0 ? (Number(summary?.categories.find(part => part.category === item.name)?.amount ?? 0) / total * 100) : 0;
        return <button key={item.name} className="orbit-category" style={{ left: `${50 + 43 * Math.cos(angle)}%`, top: `${50 + 43 * Math.sin(angle)}%`, color: color(item.name) }} type="button" disabled={disabled} aria-label={`Добавить расход: ${item.name}`} onClick={() => onCategory(item.name)}>
          <FinanceIcon name={categoryIcon(item.name)} /><span className="orbit-label"><i className="category-marker" style={{ background: color(item.name) }} aria-hidden="true" />{item.name.replace(/^[^\p{L}\p{N}]+/u, '')}</span>{share > 0 && <small>{share.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}%</small>}
        </button>;
      })}
    </div>
    {!!segments.length && <ul className="wheel-legend" aria-label="Категории на круговой диаграмме">{segments.map(segment => <li key={segment.category}>
      <span className="category-marker" style={{ background: segment.color }} aria-hidden="true" />
      <span className="wheel-legend-name">{segment.category}</span>
      <strong>{money(segment.amount)} BYN</strong><small>{Math.round(segment.share * 100)}%</small>
    </li>)}</ul>}
  </>;
}
