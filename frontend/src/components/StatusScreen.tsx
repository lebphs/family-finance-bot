interface Props {
  kind: 'loading' | 'empty' | 'error' | 'denied';
  title: string;
  description?: string;
  onRetry?: () => void;
}

export function StatusScreen({ kind, title, description, onRetry }: Props) {
  return (
    <section className={`status-card status-${kind}`} role={kind === 'error' || kind === 'denied' ? 'alert' : 'status'}>
      <span className="status-symbol" aria-hidden="true">{kind === 'loading' ? '◌' : kind === 'denied' ? '⌁' : kind === 'error' ? '!' : '—'}</span>
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {onRetry && <button className="primary-button" onClick={onRetry}>Повторить</button>}
    </section>
  );
}
