'use client';

import { TaskLogPayload } from '../lib/api';

function formatDate(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString();
}

export default function TaskLogTimeline({ logs }: { logs: TaskLogPayload[] }): JSX.Element {
  if (logs.length === 0) {
    return <div className="empty-state">尚无日志事件。</div>;
  }

  return (
    <ul className="log-list">
      {logs.map((log) => (
        <li key={log.id}>
          <span className="log-time">{formatDate(log.created_at)}</span>
          <span className="log-level" style={{ color: resolveColor(log.level) }}>
            {log.level.toUpperCase()}
          </span>
          <span className="log-message">{log.message}</span>
        </li>
      ))}
    </ul>
  );
}

function resolveColor(level: string): string {
  const upper = level.toUpperCase();
  if (upper === 'ERROR' || upper === 'FAILED') {
    return 'var(--danger)';
  }
  if (upper === 'SUCCESS' || upper === 'INFO') {
    return 'var(--accent)';
  }
  return 'var(--muted)';
}
