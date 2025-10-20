'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import {
  TaskArtifactPayload,
  TaskDetailPayload,
  TaskLogPayload,
  TaskParameter,
  TaskPlanSummary,
  TaskStatusPayload,
  apiUrl,
  taskDownloadUrl,
} from '../lib/api';
import { requestAuthorizationUrl } from '../lib/auth';
import { useUserContext } from '../contexts/UserContext';
import { ProgressBar } from './ProgressBar';
import TaskLogTimeline from './TaskLogTimeline';

function formatDate(iso: string | null): string {
  if (!iso) {
    return '-';
  }
  const date = new Date(iso);
  return date.toLocaleString();
}

export default function TaskStreamView({ taskId }: { taskId: string }): JSX.Element {
  const { user } = useUserContext();
  const userId = user?.id ?? null;
  const [status, setStatus] = useState<TaskStatusPayload | null>(null);
  const [logs, setLogs] = useState<TaskLogPayload[]>([]);
  const [artifacts, setArtifacts] = useState<TaskArtifactPayload[]>([]);
  const [artifactLoaded, setArtifactLoaded] = useState(false);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reauthError, setReauthError] = useState<string | null>(null);

  const sortedLogs = useMemo(() => {
    return [...logs].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  }, [logs]);

  const currentDescriptor = useMemo(() => {
    if (!status?.current_item) {
      return null;
    }
    const stage = status.current_stage ?? 'progress';
    const prefix = stage === 'success' ? '已完成' : stage === 'failed' ? '失败' : stage === 'skip' ? '跳过' : '正在处理';
    return `${prefix}：${status.current_item}`;
  }, [status]);

  useEffect(() => {
    if (!userId) {
      setStatus(null);
      setLogs([]);
      setConnected(false);
      setError(null);
    }
  }, [userId]);

  useEffect(() => {
    if (!userId) {
      return;
    }
    let isMounted = true;
    const controller = new AbortController();

    const connect = async () => {
      try {
        await fetchEventSource(apiUrl(`/tasks/${taskId}/stream`), {
          signal: controller.signal,
          headers: {
            'X-User-ID': userId,
          },
          onopen: () => {
            if (!isMounted) {
              return;
            }
            setConnected(true);
            setError(null);
          },
          onmessage: (event) => {
            if (!isMounted) {
              return;
            }
            if (!event.data) {
              return;
            }
            try {
              const payload = JSON.parse(event.data);
              if (event.event === 'status' || !event.event) {
                setStatus(payload as TaskStatusPayload);
              } else if (event.event === 'log') {
                setLogs((prev) => mergeLog(prev, payload as TaskLogPayload));
              }
            } catch (err) {
              console.warn('Failed to parse SSE payload', err);
            }
          },
          onerror: (err) => {
            console.error('SSE error', err);
            setConnected(false);
            setError('连接异常，稍后将自动重试...');
          },
          onclose: () => {
            setConnected(false);
            if (!controller.signal.aborted) {
              setError('连接已关闭，可刷新页面重新连接');
            }
          },
        });
      } catch (err) {
        if (controller.signal.aborted) {
          return;
        }
        console.error('SSE connection failed', err);
        setError('无法连接到任务流，请检查网络或用户 ID');
      }
    };

    void connect();

    return () => {
      isMounted = false;
      controller.abort();
      setConnected(false);
    };
  }, [taskId, userId]);

  useEffect(() => {
    if (!userId) {
      return;
    }
    const controller = new AbortController();
    const fetchInitial = async () => {
      try {
        const response = await fetch(apiUrl(`/tasks/${taskId}`), {
          headers: {
            'X-User-ID': userId,
          },
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`请求失败，状态码 ${response.status}`);
        }
        const data = (await response.json()) as TaskDetailPayload;
        const { logs: initialLogs = [], artifacts: initialArtifacts = [], ...rest } = data;
        setStatus(rest as TaskStatusPayload);
        setLogs(Array.isArray(initialLogs) ? initialLogs : []);
        setArtifacts(Array.isArray(initialArtifacts) ? initialArtifacts : []);
        setArtifactLoaded(Array.isArray(initialArtifacts) && initialArtifacts.length > 0);
      } catch (err) {
        if (!controller.signal.aborted) {
          console.error('Failed to load task detail', err);
          setError('初始化任务详情失败');
        }
      }
    };
    void fetchInitial();
    return () => controller.abort();
  }, [taskId, userId]);

  useEffect(() => {
    if (!userId || !status?.download_ready || artifactLoaded) {
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const fetchArtifacts = async () => {
      try {
        const response = await fetch(apiUrl(`/tasks/${taskId}`), {
          headers: { 'X-User-ID': userId },
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error('任务详情刷新失败');
        }
        const data = (await response.json()) as TaskDetailPayload;
        if (!cancelled) {
          setArtifacts(Array.isArray(data.artifacts) ? data.artifacts : []);
          setArtifactLoaded(true);
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          console.warn('刷新任务结果失败', err);
        }
      }
    };
    void fetchArtifacts();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [artifactLoaded, status?.download_ready, taskId, userId]);

  if (!userId) {
    return <div className="empty-state">请先登录或绑定用户 ID，才能查看任务详情。</div>;
  }

  const requiresAuth = status?.status?.toLowerCase() === 'auth_required';

  const handleReauthorize = async () => {
    try {
      const { authorization_url } = await requestAuthorizationUrl();
      window.location.href = authorization_url;
    } catch (err) {
      console.error('Failed to fetch authorization url', err);
      setReauthError(err instanceof Error ? err.message : '无法获取授权地址');
    }
  };

  useEffect(() => {
    if (!requiresAuth && reauthError) {
      setReauthError(null);
    }
  }, [requiresAuth, reauthError]);

  return (
    <div className="card">
      <div className="detail-header">
        <div>
          <Link href="/" className="back-link">
            ← 返回任务列表
          </Link>
          <h1 style={{ marginTop: 8 }}>任务 #{taskId}</h1>
          <div className={`connect-indicator ${connected ? 'connected' : 'disconnected'}`}>
            <span className="dot" /> {connected ? '实时连接已建立' : '未连接'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {status?.download_ready ? (
            <button
              className="button secondary"
              type="button"
              onClick={() => {
                const url = taskDownloadUrl(Number(taskId));
                window.open(url, '_blank', 'noopener');
              }}
            >
              下载结果
            </button>
          ) : null}
          {status ? (
            <div className="status-badge">
              <strong>{resolveStatusLabel(status.status)}</strong>
              <span>{status.task_type}</span>
            </div>
          ) : null}
        </div>
      </div>

      {status?.description ? <div className="task-description">{status.description}</div> : null}
      {status?.plan ? <PlanInsight plan={status.plan} /> : null}
      {status?.parameters?.length ? <ParameterTable parameters={status.parameters} /> : null}
      {requiresAuth ? (
        <div className="auth-warning">
          {status?.error_message ?? '授权已过期，请重新登录。'}
          <button
            className="button"
            type="button"
            style={{ marginLeft: 12 }}
            onClick={handleReauthorize}
          >
            重新授权
          </button>
          {reauthError ? <div style={{ marginTop: 6, color: 'var(--danger)' }}>{reauthError}</div> : null}
        </div>
      ) : null}

      {error ? <div style={{ marginTop: 12, color: 'var(--danger)' }}>{error}</div> : null}

      <section style={{ marginTop: 24, display: 'grid', gap: 18 }}>
        <div>
          <label>执行进度</label>
          <ProgressBar value={status?.progress ?? 0} />
          <div style={{ marginTop: 8, color: 'var(--muted)', fontSize: '0.9rem' }}>
            {status?.progress ?? 0}% ｜ 增量：{status?.incremental ? '是' : '否'}
          </div>
          {currentDescriptor ? <div style={{ marginTop: 6, color: 'var(--accent)' }}>{currentDescriptor}</div> : null}
          {status?.current_detail ? (
            <div style={{ marginTop: 4, color: 'var(--muted)', fontSize: '0.8rem' }}>{status.current_detail}</div>
          ) : null}
          {typeof status?.processed === 'number' && typeof status?.expected === 'number' ? (
            <div style={{ marginTop: 4, color: 'var(--muted)', fontSize: '0.8rem' }}>
              {`已处理 ${status.processed} / ${status.expected}`}
            </div>
          ) : null}
        </div>

        <div className="task-meta">
          <div>类型：{status?.task_type ?? '-'}</div>
          <div>创建时间：{formatDate(status?.created_at ?? null)}</div>
          <div>计划执行时间：{formatDate(status?.scheduled_for ?? null)}</div>
          <div>开始时间：{formatDate(status?.started_at ?? null)}</div>
          <div>完成时间：{formatDate(status?.completed_at ?? null)}</div>
          <div>输出：{status?.result_path ?? '-'}</div>
          {status?.error_message && !requiresAuth ? (
            <div style={{ color: 'var(--danger)' }}>错误：{status.error_message}</div>
          ) : null}
        </div>
      </section>

      {artifacts.length > 0 ? (
        <section style={{ marginTop: 28 }}>
          <h2>生成文件</h2>
          <ArtifactList artifacts={artifacts} />
        </section>
      ) : null}

      <section style={{ marginTop: 32 }}>
        <h2>执行日志</h2>
        <TaskLogTimeline logs={sortedLogs} />
      </section>
    </div>
  );
}

function PlanInsight({ plan }: { plan: TaskPlanSummary }): JSX.Element {
  const items = [
    { label: '预计处理', value: `${plan.total_files} 项` },
    { label: '预计下载', value: `${plan.will_download} 项` },
    { label: '增量跳过', value: `${plan.existing} 项` },
    { label: '其它跳过', value: `${plan.skipped} 项` },
  ];
  return (
    <div className="preview-summary" style={{ marginTop: 16 }}>
      <div className="preview-summary-grid">
        {items.map((item) => (
          <div key={item.label} className="preview-summary-item">
            <span className="label">{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
      {plan.samples?.length ? (
        <div className="preview-samples">
          <div style={{ fontWeight: 600, marginBottom: 6 }}>样例条目</div>
          <ul>
            {plan.samples.slice(0, 5).map((sample, index) => (
              <li key={`${sample.detail ?? sample.name ?? index}-${index}`}>
                <span>{sample.name ?? sample.detail ?? '未命名'}</span>
                <span style={{ color: 'var(--muted)', marginLeft: 8 }}>
                  {sample.file_type?.toUpperCase() ?? '文件'} · {resolvePlanAction(sample.action)}
                </span>
                {sample.detail ? (
                  <span style={{ color: 'var(--muted)', marginLeft: 8, fontFamily: 'monospace' }}>{sample.detail}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function ParameterTable({ parameters }: { parameters: TaskParameter[] }): JSX.Element {
  return (
    <div className="parameter-list" style={{ marginTop: 16 }}>
      <table>
        <tbody>
          {parameters.map((param) => (
            <tr key={`${param.label}-${param.value}`}>
              <td>{param.label}</td>
              <td>{param.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ArtifactList({ artifacts }: { artifacts: TaskArtifactPayload[] }): JSX.Element {
  return (
    <div className="parameter-list" style={{ marginTop: 12 }}>
      <table>
        <tbody>
          {artifacts.map((artifact, index) => (
            <tr key={`${artifact.path}-${index}`}>
              <td style={{ fontFamily: 'monospace' }}>{artifact.path}</td>
              <td>{artifact.file_type?.toUpperCase() ?? '-'}</td>
              <td>{formatDate(artifact.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function resolvePlanAction(action: string): string {
  const lower = action.toLowerCase();
  if (lower === 'download') {
    return '将下载';
  }
  if (lower === 'existing') {
    return '已存在';
  }
  if (lower === 'skip') {
    return '跳过';
  }
  return action;
}

function mergeLog(existing: TaskLogPayload[], incoming: TaskLogPayload): TaskLogPayload[] {
  const has = existing.some((entry) => entry.id === incoming.id);
  if (has) {
    return existing.map((entry) => (entry.id === incoming.id ? incoming : entry));
  }
  return [...existing, incoming];
}

function resolveStatusLabel(status: string): string {
  const lower = status.toLowerCase();
  switch (lower) {
    case 'pending':
      return '待执行';
    case 'queued':
      return '排队中';
    case 'scheduled':
      return '已计划';
    case 'running':
      return '执行中';
    case 'completed':
      return '已完成';
    case 'failed':
      return '失败';
    case 'cancelled':
      return '已取消';
    case 'auth_required':
      return '需重新授权';
    default:
      return status.toUpperCase();
  }
}
