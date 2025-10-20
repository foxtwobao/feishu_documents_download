'use client';

import { FormEvent, useCallback, useMemo, useState } from 'react';
import {
  TaskPlanSummary,
  TaskParameter,
  TaskPlanSample,
  TaskPreviewResponse,
  fetchTaskPreview,
  apiUrl,
} from '../lib/api';
import { requestAuthorizationUrl } from '../lib/auth';

const TASK_OPTIONS = [
  { value: 'space', label: '个人空间同步（Drive Space）', requiresToken: false },
  { value: 'docx', label: '单文档下载（Doc/Docx）', requiresToken: true },
  { value: 'folder', label: '文件夹同步', requiresToken: true },
  { value: 'sheet', label: '电子表格（Sheet）导出', requiresToken: true },
  { value: 'bitable', label: '多维表（Bitable）导出', requiresToken: true },
];

type TaskCreatorProps = {
  userId: string;
  onCreated?: () => void;
  onSwitchTab?: (tab: 'create' | 'tasks') => void;
};

type WizardStep = 'configure' | 'preview';

export default function TaskCreator({ userId, onCreated, onSwitchTab }: TaskCreatorProps): JSX.Element {
  const [taskType, setTaskType] = useState<string>('space');
  const [token, setToken] = useState('');
  const [name, setName] = useState('');
  const [parentPath, setParentPath] = useState('.');
  const [limit, setLimit] = useState('');
  const [incremental, setIncremental] = useState(true);
  const [scheduleAt, setScheduleAt] = useState('');
  const [extraPayload, setExtraPayload] = useState('');

  const [step, setStep] = useState<WizardStep>('configure');
  const [preview, setPreview] = useState<TaskPreviewResponse | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [reauthError, setReauthError] = useState<string | null>(null);
  const [reauthLoading, setReauthLoading] = useState(false);

  const currentOption = useMemo(() => TASK_OPTIONS.find((item) => item.value === taskType), [taskType]);

  const resetForm = useCallback(() => {
    setToken('');
    setName('');
    setParentPath('.');
    setLimit('');
    setIncremental(true);
    setScheduleAt('');
    setExtraPayload('');
    setPreview(null);
    setStep('configure');
    setAuthRequired(false);
    setReauthError(null);
    setReauthLoading(false);
  }, []);

  const handleReauthorize = useCallback(async () => {
    try {
      setReauthLoading(true);
      const { authorization_url } = await requestAuthorizationUrl();
      window.location.href = authorization_url;
    } catch (err) {
      console.error('Failed to fetch authorization url', err);
      setReauthError(err instanceof Error ? err.message : '无法获取授权地址');
      setReauthLoading(false);
    }
  }, []);

  const buildBasePayload = useCallback((): Record<string, unknown> => {
    const payload: Record<string, unknown> = {};
    const trimmedToken = token.trim();
    const trimmedName = name.trim();
    const trimmedParent = parentPath.trim() || '.';
    if (trimmedToken) {
      payload.token = trimmedToken;
    }
    if (trimmedName) {
      payload.name = trimmedName;
    }
    payload.parent_path = trimmedParent;

    if (extraPayload.trim()) {
      try {
        const parsed = JSON.parse(extraPayload);
        if (typeof parsed === 'object' && parsed !== null) {
          Object.assign(payload, parsed);
        }
      } catch (err) {
        throw new Error('扩展参数必须是合法的 JSON 字符串');
      }
    }
    return payload;
  }, [token, name, parentPath, extraPayload]);

  const handlePreview = useCallback(async () => {
    setError(null);
    setMessage(null);
    setAuthRequired(false);
    setReauthError(null);
    if (currentOption?.requiresToken && !token.trim()) {
      setError('该任务类型需要输入 token');
      return;
    }
    let previewPayload: Record<string, unknown>;
    try {
      previewPayload = buildBasePayload();
    } catch (err) {
      setError(err instanceof Error ? err.message : '扩展参数解析失败');
      return;
    }
    const parsedLimit = limit.trim() ? Number(limit.trim()) : null;
    if (parsedLimit !== null && Number.isNaN(parsedLimit)) {
      setError('最大处理条数必须是数字');
      return;
    }
    setLoadingPreview(true);
    try {
      const response = await fetchTaskPreview(userId, {
        task_type: taskType,
        payload: previewPayload,
        incremental,
        limit: parsedLimit,
      });
      setPreview(response);
      setStep('preview');
    } catch (err) {
      if (err && (err as Error & { authRequired?: boolean }).authRequired) {
        setError(null);
        setAuthRequired(true);
        setStep('configure');
      } else {
        setError(err instanceof Error ? err.message : '生成任务预览失败');
      }
    } finally {
      setLoadingPreview(false);
    }
  }, [buildBasePayload, currentOption?.requiresToken, incremental, limit, taskType, token, userId]);

  const handleCreate = useCallback(
    async (event?: FormEvent<HTMLFormElement>) => {
      event?.preventDefault();
      setError(null);
      setMessage(null);
      let basePayload: Record<string, unknown>;
      try {
        basePayload = buildBasePayload();
      } catch (err) {
        setError(err instanceof Error ? err.message : '扩展参数解析失败');
        return;
      }
      const trimmedLimit = limit.trim();
      const parsedLimit = trimmedLimit ? Number(trimmedLimit) : null;
      if (parsedLimit !== null && Number.isNaN(parsedLimit)) {
        setError('最大处理条数必须是数字');
        return;
      }
      let scheduleIso: string | null = null;
      if (scheduleAt) {
        const dt = new Date(scheduleAt);
        if (Number.isNaN(dt.getTime())) {
          setError('请选择有效的计划时间');
          return;
        }
        scheduleIso = dt.toISOString();
      }
      const payloadForRequest: Record<string, unknown> = { ...basePayload };
      delete payloadForRequest.extra;
      if (preview?.plan) {
        payloadForRequest._plan_summary = preview.plan;
      }
      payloadForRequest._description = buildDescription(taskType, payloadForRequest, incremental, parsedLimit);
      setSubmitting(true);
      try {
        const response = await fetch(apiUrl('/tasks'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-User-ID': userId,
          },
          body: JSON.stringify({
            task_type: taskType,
            payload: payloadForRequest,
            incremental,
            limit: parsedLimit,
            schedule_at: scheduleIso,
          }),
        });
        if (response.status === 401) {
          const authError = new Error('auth_required');
          (authError as Error & { authRequired?: boolean }).authRequired = true;
          throw authError;
        }
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `任务创建失败（${response.status}）`);
        }
        setMessage('任务已创建并进入队列。');
        onCreated?.();
        resetForm();
        onSwitchTab?.('tasks');
      } catch (err) {
      if (err && (err as Error & { authRequired?: boolean }).authRequired) {
        setError(null);
        setAuthRequired(true);
        setStep('configure');
        setMessage(null);
      } else {
        setError(err instanceof Error ? err.message : '任务创建失败');
      }
    } finally {
      setSubmitting(false);
    }
  },
    [
      buildBasePayload,
      extraPayload,
      incremental,
      limit,
      onCreated,
      onSwitchTab,
      preview?.plan,
      resetForm,
      scheduleAt,
      taskType,
      userId,
    ],
  );

  const parametersPreview: TaskParameter[] = useMemo(() => {
    try {
      const payload = buildBasePayload();
      return buildParameterList(taskType, payload, incremental, limit);
    } catch {
      return buildParameterList(taskType, {}, incremental, limit);
    }
  }, [buildBasePayload, incremental, limit, taskType]);

  if (step === 'preview' && preview) {
    return (
      <div className="card" style={{ display: 'grid', gap: 18 }}>
        <header>
          <h2>任务预览</h2>
          <p style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>
            请确认参数与预估影响，确认后将立即创建同步任务。
          </p>
        </header>

        <section style={{ display: 'grid', gap: 12 }}>
          <PreviewSummary plan={preview.plan} />
          <ParameterList parameters={parametersPreview} />
        </section>

        {error ? <div style={{ color: 'var(--danger)' }}>{error}</div> : null}
        {message ? <div style={{ color: 'var(--success)' }}>{message}</div> : null}

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              setStep('configure');
            }}
            disabled={submitting}
          >
            上一步
          </button>
          <button type="button" className="button" onClick={() => void handleCreate()} disabled={submitting}>
            {submitting ? '创建中...' : '确认创建'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      className="card"
      style={{ marginBottom: 24, display: 'grid', gap: 16 }}
      onSubmit={(event) => {
        event.preventDefault();
        void handlePreview();
      }}
    >
      <h2>创建同步任务</h2>
      <div>
        <label htmlFor="taskType">任务类型</label>
        <select id="taskType" value={taskType} onChange={(event) => setTaskType(event.target.value)}>
          {TASK_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {authRequired ? (
        <div className="auth-warning" style={{ marginTop: -8 }}>
          授权已过期，请重新登录。
          <button
            className="button"
            type="button"
            style={{ marginLeft: 12 }}
            onClick={() => {
              setReauthError(null);
              void handleReauthorize();
            }}
            disabled={reauthLoading}
          >
            {reauthLoading ? '跳转中...' : '重新授权'}
          </button>
          {reauthError ? <div style={{ marginTop: 6 }}>{reauthError}</div> : null}
        </div>
      ) : null}

      {currentOption?.requiresToken ? (
        <div>
          <label htmlFor="token">目标 token</label>
          <input
            id="token"
            placeholder="请输入文件/文件夹 token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
        </div>
      ) : null}

      <div className="form-inline" style={{ gap: 16 }}>
        <div style={{ flex: 1 }}>
          <label htmlFor="name">任务名称（可选）</label>
          <input
            id="name"
            placeholder="若不填写将使用远端名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div style={{ flex: 1 }}>
          <label htmlFor="parentPath">输出目录</label>
          <input
            id="parentPath"
            placeholder="例如：ProjectA"
            value={parentPath}
            onChange={(event) => setParentPath(event.target.value)}
          />
        </div>
      </div>

      <div className="form-inline" style={{ gap: 16 }}>
        <div>
          <label htmlFor="incremental">增量模式</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              id="incremental"
              type="checkbox"
              checked={incremental}
              onChange={(event) => setIncremental(event.target.checked)}
              style={{ width: 16, height: 16 }}
            />
            <span style={{ color: 'var(--muted)', fontSize: '0.85rem' }}>开启增量同步</span>
          </div>
        </div>
        <div>
          <label htmlFor="limit">最大处理条数（可选）</label>
          <input
            id="limit"
            type="number"
            min="1"
            placeholder="例如：100"
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="schedule">计划执行时间（可选）</label>
          <input
            type="datetime-local"
            id="schedule"
            value={scheduleAt}
            onChange={(event) => setScheduleAt(event.target.value)}
          />
        </div>
      </div>

      <div>
        <label htmlFor="extraPayload">额外参数（JSON，可选）</label>
        <textarea
          id="extraPayload"
          rows={3}
          placeholder='例如：{"parent_path": "ProjectA"}'
          value={extraPayload}
          onChange={(event) => setExtraPayload(event.target.value)}
          style={{
            background: 'rgba(15, 23, 42, 0.4)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: '10px 12px',
            color: 'var(--text)',
            width: '100%',
            fontFamily: 'monospace',
          }}
        />
      </div>

      {loadingPreview ? (
        <div className="auth-warning" style={{ background: 'rgba(56, 189, 248, 0.12)', borderColor: 'rgba(56, 189, 248, 0.4)', color: 'var(--accent)' }}>
          正在生成任务预览，请稍候...
        </div>
      ) : null}
      {error ? <div style={{ color: 'var(--danger)' }}>{error}</div> : null}
      {message ? <div style={{ color: 'var(--success)' }}>{message}</div> : null}

      <button type="submit" className="button" style={{ justifyContent: 'center' }} disabled={loadingPreview}>
        {loadingPreview ? '计算预览中...' : '下一步'}
      </button>
    </form>
  );
}

function buildDescription(
  taskType: string,
  payload: Record<string, unknown>,
  incremental: boolean,
  limit: number | null,
): string {
  const mode = (taskType || '').toLowerCase();
  const incrementLabel = incremental ? '增量' : '全量';
  const limitNote = limit ? `，最多处理 ${limit} 项` : '';
  if (mode === 'space' || mode === 'drive_space' || mode === 'full') {
    return `${incrementLabel}同步个人空间${limitNote}`;
  }
  const targetName = String(payload.name ?? payload.token ?? '未命名');
  const parent = String(payload.parent_path ?? '.');
  return `${incrementLabel}下载 ${mode.toUpperCase()}「${targetName}」到 ${parent}${limitNote}`;
}

function buildParameterList(
  taskType: string,
  payload: Record<string, unknown>,
  incremental: boolean,
  limit: string | number | null,
): TaskParameter[] {
  const params: TaskParameter[] = [];
  if (payload.name) {
    params.push({ label: '名称', value: String(payload.name) });
  }
  if (payload.token) {
    params.push({ label: 'Token', value: String(payload.token) });
  }
  params.push({ label: '输出目录', value: String(payload.parent_path ?? '.') });
  params.push({ label: '增量模式', value: incremental ? '是' : '否' });
  if (limit && !Number.isNaN(Number(limit))) {
    params.push({ label: '最大处理数量', value: String(limit) });
  }
  const knownKeys = new Set(['name', 'token', 'parent_path']);
  Object.entries(payload).forEach(([key, value]) => {
    if (knownKeys.has(key) || key.startsWith('_')) {
      return;
    }
    params.push({ label: `扩展：${key}`, value: typeof value === 'object' ? JSON.stringify(value) : String(value) });
  });
  params.push({ label: '类型', value: taskType.toUpperCase() });
  return params;
}

function PreviewSummary({ plan }: { plan: TaskPlanSummary }): JSX.Element {
  const items: { label: string; value: string }[] = [
    { label: '预计处理', value: `${plan.total_files} 项` },
    { label: '预计下载', value: `${plan.will_download} 项` },
    { label: '增量跳过', value: `${plan.existing} 项` },
    { label: '其它跳过', value: `${plan.skipped} 项` },
  ];
  return (
    <div className="preview-summary">
      <div className="preview-summary-grid">
        {items.map((item) => (
          <div key={item.label} className="preview-summary-item">
            <span className="label">{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function ParameterList({ parameters }: { parameters: TaskParameter[] }): JSX.Element {
  return (
    <div className="parameter-list">
      <div style={{ fontWeight: 600 }}>参数概览</div>
      <table>
        <tbody>
          {parameters.map((param) => (
            <tr key={param.label}>
              <td>{param.label}</td>
              <td>{param.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function resolveAction(action: string): string {
  if (action === 'download') {
    return '将下载';
  }
  if (action === 'existing') {
    return '已存在';
  }
  if (action === 'skip') {
    return '跳过';
  }
  return action;
}
