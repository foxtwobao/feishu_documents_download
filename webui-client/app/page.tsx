'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import UserGate from '../components/UserGate';
import TaskCreator from '../components/TaskCreator';
import { ProgressBar } from '../components/ProgressBar';
import { TaskListResponse, TaskPlanSummary, TaskStatusPayload, apiUrl } from '../lib/api';
import { fetchUserProfile, requestAuthorizationUrl } from '../lib/auth';
import { useUserContext } from '../contexts/UserContext';

type TabKey = 'create' | 'tasks' | 'guide';

export default function TaskListPage(): JSX.Element {
  return (
    <UserGate>
      <TaskConsole />
    </UserGate>
  );
}

function TaskConsole(): JSX.Element {
  const { user, setUser } = useUserContext();
  const userId = user?.id ?? null;
  const [tasks, setTasks] = useState<TaskStatusPayload[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshFlag, setRefreshFlag] = useState(0);
  const [nextRefreshSilent, setNextRefreshSilent] = useState(false);
  const [actionTaskId, setActionTaskId] = useState<number | null>(null);
  const [actionType, setActionType] = useState<'start' | 'cancel' | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('create');

  useEffect(() => {
    if (!userId) {
      setTasks([]);
      setLoading(false);
      setError(null);
    }
  }, [userId]);

  useEffect(() => {
    if (!user || user.displayName) {
      return;
    }
    let cancelled = false;
    const hydrate = async () => {
      try {
        const profile = await fetchUserProfile(user.id);
        if (!cancelled) {
          setUser(profile);
        }
      } catch (err) {
        console.warn('Failed to hydrate user profile', err);
      }
    };
    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [setUser, user]);

  useEffect(() => {
    if (!userId) {
      return;
    }
    const controller = new AbortController();
    const loadTasks = async (silent: boolean) => {
      try {
        if (!silent) {
          setLoading(true);
        }
        const response = await fetch(apiUrl('/tasks'), {
          headers: { 'X-User-ID': userId },
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`请求失败，状态码 ${response.status}`);
        }
        const data = (await response.json()) as TaskListResponse;
        setTasks(data.tasks ?? []);
        setError(null);
      } catch (err) {
        if (!controller.signal.aborted) {
          console.error('Failed to fetch tasks', err);
          setError('加载任务列表失败');
        }
      } finally {
        if (!controller.signal.aborted && !silent) {
          setLoading(false);
        }
        setNextRefreshSilent(true);
      }
    };
    void loadTasks(nextRefreshSilent);
    return () => controller.abort();
  }, [nextRefreshSilent, refreshFlag, userId]);

  const triggerRefresh = useCallback((silent = false) => {
    setNextRefreshSilent(silent);
    setRefreshFlag((value) => value + 1);
  }, []);

  const handleAction = useCallback(
    async (taskId: number, action: 'start' | 'cancel') => {
      if (!userId) {
        return;
      }
      setActionTaskId(taskId);
      setActionType(action);
      try {
        const endpoint = action === 'start' ? `/tasks/${taskId}/retry` : `/tasks/${taskId}/cancel`;
        const response = await fetch(apiUrl(endpoint), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-User-ID': userId,
          },
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `操作失败（${response.status}）`);
        }
        triggerRefresh();
        setTimeout(() => {
          triggerRefresh(true);
        }, 1500);
        setError(null);
      } catch (err) {
        console.error('Task action failed', err);
        setError(err instanceof Error ? err.message : '操作失败');
      } finally {
        setActionTaskId(null);
        setActionType(null);
      }
    },
    [triggerRefresh, userId],
  );

  const hasActiveTask = useMemo(
    () => tasks.some((task) => ['queued', 'scheduled', 'running'].includes(task.status.toLowerCase())),
    [tasks],
  );

  useEffect(() => {
    if (!userId || !hasActiveTask) {
      return;
    }
    const timer = setInterval(() => {
      triggerRefresh(true);
    }, 2500);
    return () => clearInterval(timer);
  }, [userId, hasActiveTask, triggerRefresh]);
  const handleDownload = useCallback(
    async (taskId: number) => {
      if (!userId) {
        return;
      }
      try {
        const downloadUrl = apiUrl(`/tasks/${taskId}/download?user_id=${encodeURIComponent(userId)}`);
        const response = await fetch(downloadUrl, {
          headers: { 'X-User-ID': userId },
        });
        if (response.status === 401) {
          setError('需重新授权后才能下载。');
          return;
        }
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `下载失败（${response.status}）`);
        }
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = `task-${taskId}.zip`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(objectUrl);
      } catch (err) {
        console.error('Download failed', err);
        setError(err instanceof Error ? err.message : '下载失败');
      }
    },
    [userId],
  );

  const handleReauthorize = useCallback(async () => {
    try {
      const { authorization_url } = await requestAuthorizationUrl();
      window.location.href = authorization_url;
    } catch (err) {
      console.error('Failed to fetch authorization url', err);
      setError(err instanceof Error ? err.message : '无法获取授权地址');
    }
  }, []);

  const tabContent = useMemo(() => {
    if (activeTab === 'guide') {
      return <GuidePanel />;
    }
    if (activeTab === 'tasks') {
      return (
        <TaskListPanel
          tasks={tasks}
          loading={loading}
          error={error}
          userId={userId}
          userName={user?.displayName ?? null}
          triggerRefresh={triggerRefresh}
          setUser={setUser}
          onAction={handleAction}
          actionTaskId={actionTaskId}
          actionType={actionType}
          onDownload={handleDownload}
          onReauthorize={handleReauthorize}
        />
      );
    }
    return null;
  }, [
    activeTab,
    actionTaskId,
    actionType,
    error,
    handleAction,
    handleDownload,
    loading,
    setUser,
    tasks,
    triggerRefresh,
    user?.displayName,
    userId,
    handleReauthorize,
  ]);

  if (!userId) {
    return <div className="empty-state">请先登录或绑定用户 ID。</div>;
  }

  return (
    <div style={{ display: 'grid', gap: 24 }}>
      <TabSwitcher activeTab={activeTab} onChange={setActiveTab} />
      {activeTab === 'create' ? (
        <TaskCreator
          userId={userId}
          onCreated={() => {
            triggerRefresh();
            setActiveTab('tasks');
          }}
          onSwitchTab={setActiveTab}
        />
      ) : null}
      {tabContent}
    </div>
  );
}

function TabSwitcher({ activeTab, onChange }: { activeTab: TabKey; onChange: (tab: TabKey) => void }): JSX.Element {
  const tabs: { key: TabKey; label: string }[] = [
    { key: 'create', label: '创建任务' },
    { key: 'tasks', label: '我的任务' },
    { key: 'guide', label: '使用指南' },
  ];
  return (
    <div className="tab-switcher">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          className={tab.key === activeTab ? 'active' : ''}
          type="button"
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

type TaskListPanelProps = {
  tasks: TaskStatusPayload[];
  userId: string | null;
  userName: string | null;
  loading: boolean;
  error: string | null;
  triggerRefresh: () => void;
  setUser: (value: unknown) => void;
  onAction: (taskId: number, action: 'start' | 'cancel') => void;
  actionTaskId: number | null;
  actionType: 'start' | 'cancel' | null;
  onDownload: (taskId: number) => void;
  onReauthorize: () => void;
};

function TaskListPanel({
  tasks,
  userId,
  userName,
  loading,
  error,
  triggerRefresh,
  setUser,
  onAction,
  actionTaskId,
  actionType,
  onDownload,
  onReauthorize,
}: TaskListPanelProps): JSX.Element {
  return (
    <div className="card" style={{ display: 'grid', gap: 18 }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>同步任务总览</h1>
          <span style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>
            当前用户：{userName ? `${userName}（ID: ${userId}）` : userId}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button className="button" onClick={triggerRefresh}>
            刷新
          </button>
          <button
            className="button"
            onClick={() => {
              setUser(null);
            }}
          >
            退出登录
          </button>
        </div>
      </header>

      {loading ? <div className="empty-state">加载中...</div> : null}
      {error ? <div style={{ color: 'var(--danger)' }}>{error}</div> : null}

      {!loading && tasks.length === 0 ? (
        <div className="empty-state">暂无任务，您可以在“创建任务”页签创建新的同步任务。</div>
      ) : null}

      <div className="tasks-grid">
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onAction={onAction}
            actionTaskId={actionTaskId}
            actionType={actionType}
            onDownload={onDownload}
            onReauthorize={onReauthorize}
          />
        ))}
      </div>
    </div>
  );
}

function TaskCard({
  task,
  onAction,
  actionTaskId,
  actionType,
  onDownload,
  onReauthorize,
}: {
  task: TaskStatusPayload;
  onAction: (taskId: number, action: 'start' | 'cancel') => void;
  actionTaskId: number | null;
  actionType: 'start' | 'cancel' | null;
  onDownload: (taskId: number) => void;
  onReauthorize: () => void;
}): JSX.Element {
  const detailLines: string[] = [];
  if (task.description) {
    detailLines.push(task.description);
  }
  if (task.parameters && task.parameters.length > 0) {
    detailLines.push(task.parameters.map((param) => `${param.label}: ${param.value}`).join(' ｜ '));
  }
  const planSummary = summarizePlan(task.plan);
  const statusLower = task.status.toLowerCase();
  const canStart = ['pending', 'failed', 'cancelled', 'queued', 'scheduled', 'completed'].includes(statusLower);
  const canCancel = statusLower === 'running' || statusLower === 'queued' || statusLower === 'scheduled';
  const busy = actionTaskId === task.id;
  const requiresAuth = statusLower === 'auth_required';
  const statusLabel = resolveStatusLabel(task.status);

  const cardClass = `task-card${statusLower === 'running' ? ' task-card--running' : ''}`;

  return (
    <Link key={task.id} href={`/tasks/${task.id}`} className={cardClass}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <strong>任务 #{task.id}</strong>
          <div style={{ marginTop: 4, color: 'var(--muted)' }}>{task.task_type}</div>
        </div>
        <div className="status-badge" style={{ fontSize: '0.75rem' }}>
          {statusLabel}
        </div>
      </div>
      {detailLines.length > 0 ? (
        <div className="task-description">
          {detailLines.map((line, index) => (
            <div key={index}>{line}</div>
          ))}
        </div>
      ) : null}
      <div style={{ marginTop: 12 }}>
        <ProgressBar value={task.progress} />
        <div style={{ marginTop: 8, color: 'var(--muted)', fontSize: '0.85rem' }}>{task.progress}%</div>
      </div>
      {planSummary ? <PlanBadge summary={planSummary} /> : null}
      <div className="task-meta">
        <span>创建：{new Date(task.created_at).toLocaleString()}</span>
        {task.started_at ? <span>开始：{new Date(task.started_at).toLocaleString()}</span> : null}
        {task.completed_at ? <span>完成：{new Date(task.completed_at).toLocaleString()}</span> : null}
      </div>
      <div style={{ marginTop: 16, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {requiresAuth ? (
          <button
            className="button"
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onReauthorize();
            }}
          >
            重新授权
          </button>
        ) : null}
        {!requiresAuth ? (
          <>
            <button
              className="button"
              type="button"
              disabled={!canStart || busy}
              aria-disabled={!canStart || busy}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                void onAction(task.id, 'start');
              }}
              style={{ opacity: !canStart || busy ? 0.6 : 1 }}
            >
              {busy && actionType === 'start' ? '启动中...' : '开始'}
            </button>
            <button
              className="button"
              type="button"
              disabled={!canCancel || busy}
              aria-disabled={!canCancel || busy}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                void onAction(task.id, 'cancel');
              }}
              style={{ opacity: !canCancel || busy ? 0.6 : 1 }}
            >
              {busy && actionType === 'cancel' ? '终止中...' : '终止'}
            </button>
            {task.download_ready ? (
              <button
                className="button secondary"
                type="button"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onDownload(task.id);
                }}
              >
                下载结果
              </button>
            ) : null}
          </>
        ) : null}
      </div>
      {task.error_message ? (
        requiresAuth ? (
          <div className="auth-warning">{task.error_message}</div>
        ) : (
          <div style={{ marginTop: 12, color: 'var(--danger)', fontSize: '0.9rem' }}>{task.error_message}</div>
        )
      ) : null}
    </Link>
  );
}

function summarizePlan(plan?: TaskPlanSummary | null): string | null {
  if (!plan) {
    return null;
  }
  const total = plan.total_files ?? 0;
  const download = plan.will_download ?? 0;
  if (total === 0 && download === 0) {
    return null;
  }
  if (total === download) {
    return `预计下载 ${download} 项`;
  }
  return `预计下载 ${download} / 共 ${total}`;
}

function PlanBadge({ summary }: { summary: string | null }): JSX.Element | null {
  if (!summary) {
    return null;
  }
  return (
    <div className="plan-badge" style={{ marginTop: 8 }}>
      {summary}
    </div>
  );
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

function GuidePanel(): JSX.Element {
  return (
    <div className="card" style={{ display: 'grid', gap: 12 }}>
      <h2>使用指南</h2>
      <p>
        在“创建任务”页签按向导配置同步参数后，可先查看任务预估的下载范围与样例，再确认创建。同步完成后可在任务详情页或列表中下载打包结果。
      </p>
      <ul className="guide-list">
        <li>单文档 / 文件任务会生成 Markdown 或导出文件，并保留附件与图片。</li>
        <li>空间同步会根据增量策略跳过未变更的文件，预览中可查看预计下载数量。</li>
        <li>任务执行完成后，点击“下载结果”可获取打包好的 ZIP 文件。</li>
        <li>如需重新执行失败或完成的任务，可点击“开始”按钮重新入队。</li>
      </ul>
    </div>
  );
}
