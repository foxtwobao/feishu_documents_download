'use client';

export function ProgressBar({ value }: { value: number }): JSX.Element {
  const pct = Math.min(Math.max(value, 0), 100);
  return (
    <div className="progress-shell">
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
