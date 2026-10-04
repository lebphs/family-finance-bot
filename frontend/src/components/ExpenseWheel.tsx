import { Category, HomeSummary } from '../api';
import { categoryColors, categoryIcon, FinanceIcon } from './FinanceIcon';
const money = (value: string) => Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export function ExpenseWheel({ categories, summary, onCategory, disabled }: { categories: Category[]; summary: HomeSummary | null; onCategory: (name: string) => void; disabled: boolean }) {
  const total = Number(summary?.total ?? 0);
  let offset = 0;
  const segments = (summary?.categories ?? []).map((item) => {
    const share = total > 0 ? Math.max(0, Number(item.amount) / total) : 0;
    const start = offset; offset += share;
    const index = categories.findIndex((category) => category.name === item.category);
    return { ...item, share, start, color: categoryColors[(index < 0 ? 0 : index) % categoryColors.length] };
  });
  const orbit = categories.slice(0, 12);
  return <div className="expense-wheel">
    <svg className="donut" viewBox="0 0 200 200" aria-hidden="true">
      <circle cx="100" cy="100" r="78" fill="none" stroke="var(--ring-empty)" strokeWidth="35" />
      {segments.map((segment) => <circle key={segment.category} cx="100" cy="100" r="78" fill="none" stroke={segment.color} strokeWidth="35" pathLength="1" strokeDasharray={`${segment.share} ${1 - segment.share}`} strokeDashoffset={-segment.start} transform="rotate(-90 100 100)" />)}
    </svg>
    <div className="donut-total"><span>Расходы за месяц</span><strong>{summary ? money(summary.total) : '…'}</strong><span>BYN</span></div>
    {orbit.map((item, index) => {
      const angle = (-120 + index * 360 / Math.max(orbit.length, 6)) * Math.PI / 180;
      const share = total > 0 ? (Number(summary?.categories.find((part) => part.category === item.name)?.amount ?? 0) / total * 100) : 0;
      return <button key={item.name} className="orbit-category" style={{ left: `${50 + 43 * Math.cos(angle)}%`, top: `${50 + 43 * Math.sin(angle)}%`, color: categoryColors[index % categoryColors.length] }} type="button" disabled={disabled} aria-label={`Добавить расход: ${item.name}`} onClick={() => onCategory(item.name)}>
        <FinanceIcon name={categoryIcon(item.name)} /><span>{item.name}</span>{share > 0 && <small>{share.toLocaleString('ru-RU', { maximumFractionDigits: 0 })}%</small>}
      </button>;
    })}
  </div>;
}
