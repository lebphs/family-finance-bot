import { MonthTotal, ParticipantStatistics } from '../api';

const colors = ['#91b9ff', '#70d6cf', '#c6a1f5', '#ffc887', '#f394ad', '#b3d68c'];
const amount = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
const monthLabel = (month: string) => new Intl.DateTimeFormat('ru-RU', { month: 'short', year: '2-digit', timeZone: 'UTC' }).format(new Date(`${month}-01T00:00:00Z`));

export function ParticipantMonthlyChart({ months, participants, monthly }: { months: string[]; participants: ParticipantStatistics[]; monthly?: MonthTotal[] }) {
  const values = participants.map(person => months.map(month => Number(person.monthly.find(item => item.month === month)?.total ?? 0)));
  const maximum = Math.max(0, ...values.flat());
  const roughStep = (maximum || 100) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const step = [1, 2, 5, 10].map(n => n * magnitude).find(n => n >= roughStep)!;
  const ceiling = Math.ceil((maximum || 100) / step) * step;
  const ticks = Array.from({ length: Math.round(ceiling / step) + 1 }, (_, i) => i * step);
  const left = 64, top = 28, plotHeight = 210;
  const groupWidth = Math.max(64, participants.length * 14 + 18);
  const width = Math.max(280, left + months.length * groupWidth + 20);
  const plotWidth = width - left - 20;
  const group = plotWidth / Math.max(1, months.length);
  const barWidth = Math.min(28, (group - 24) / Math.max(1, participants.length));
  return <section className="home-card" aria-labelledby="participant-monthly-title">
    <h2 id="participant-monthly-title">Расходы по месяцам и участникам</h2>
    {participants.length ? <>
      <ul className="chart-legend" aria-label="Участники графика">{participants.map((person, i) => <li key={person.author_id ?? 'unknown'}><span className="chart-swatch" style={{ background: colors[i % colors.length] }} aria-hidden="true" />{person.author_name}</li>)}</ul>
      <div className="monthly-chart-scroll">
        <svg className="monthly-chart" style={{ minWidth: width }} viewBox={`0 0 ${width} 292`} role="img" aria-label="Столбчатый график расходов по месяцам и участникам">
          <title>Месяцы и расходы каждого участника в BYN</title>
          <desc>По горизонтали — месяцы, по вертикали — сумма в BYN. Цвета столбцов обозначают участников; точные суммы доступны в таблице ниже.</desc>
          <text x={left} y={14}>BYN</text>
          {ticks.map(tick => {
            const y = top + plotHeight * (1 - tick / ceiling);
            return <g key={tick}><line className="chart-grid" x1={left} x2={width - 20} y1={y} y2={y} /><text x={left - 10} y={y + 4} textAnchor="end">{amount(tick)}</text></g>;
          })}
          <line className="chart-axis" x1={left} x2={left} y1={top} y2={top + plotHeight} />
          <line className="chart-axis" x1={left} x2={width - 20} y1={top + plotHeight} y2={top + plotHeight} />
          {months.map((month, m) => <g key={`${month}-${m}`}>
            {participants.map((person, p) => {
              const value = values[p][m], height = value / ceiling * plotHeight;
              const x = left + group * m + (group - barWidth * participants.length) / 2 + p * barWidth;
              return <rect key={person.author_id ?? 'unknown'} x={x + 2} y={top + plotHeight - height} width={Math.max(1, barWidth - 4)} height={height} rx={3} fill={colors[p % colors.length]}><title>{person.author_name} · {month}: {amount(value)} BYN</title></rect>;
            })}
            <text x={left + group * (m + .5)} y={top + plotHeight + 26} textAnchor="middle">{monthLabel(month)}</text>
          </g>)}
        </svg>
      </div>
      <details className="participant-statistics"><summary>Суммы по месяцам</summary>
        <div className="monthly-chart-scroll"><table className="chart-table">
          <caption>Расходы участников, BYN</caption>
          <thead><tr><th scope="col">Месяц</th><th scope="col">Изменение, %</th><th scope="col">Всего, BYN</th>{participants.map(person => <th scope="col" key={person.author_id ?? 'unknown'}>{person.author_name}</th>)}</tr></thead>
          <tbody>{months.map((month, m) => {
            const total = monthly?.find(item => item.month === month);
            const value = total ? Number(total.total) : values.reduce((sum, series) => sum + series[m], 0);
            const previous = m ? values.reduce((sum, series) => sum + series[m - 1], 0) : 0;
            const change = total ? total.change_percent : m && previous ? String((value / previous - 1) * 100) : null;
            return <tr key={`${month}-${m}`}><th scope="row">{month}</th><td>{change === null ? '—' : `${Number(change) > 0 ? '+' : ''}${amount(Number(change))} %`}</td><td>{amount(value)}</td>{participants.map((person, p) => <td key={person.author_id ?? 'unknown'}>{amount(values[p][m])}</td>)}</tr>;
          })}</tbody>
        </table></div>
        <p className="chart-note">Изменение общей суммы относительно предыдущего показанного месяца. «—» — нет базовой суммы или она равна нулю.</p>
      </details>
    </> : <p>За выбранные месяцы пока нет расходов участников.</p>}
  </section>;
}
