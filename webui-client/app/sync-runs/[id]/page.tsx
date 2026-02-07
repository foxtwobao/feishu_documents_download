'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { initializeAuth, SessionUser } from '@/lib/auth';
import api, { SyncRun, User, SyncFileRecord, FileStatus } from '@/lib/api';
import Shell from '@/components/Shell';
import AccessDenied from '@/components/AccessDenied';

// File list modal type
type FileModalType = 'downloaded' | 'skipped' | 'failed' | null;

export default function SyncRunDetailPage() {
  const router = useRouter();
  const params = useParams();
  const runId = parseInt(params.id as string);
  
  const [user, setUser] = useState<SessionUser | null>(null);
  const [userProfile, setUserProfile] = useState<User | null>(null);
  const [run, setRun] = useState<SyncRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  
  // File list modal state
  const [modalType, setModalType] = useState<FileModalType>(null);
  const [modalFiles, setModalFiles] = useState<SyncFileRecord[]>([]);
  const [modalLoading, setModalLoading] = useState(false);

  useEffect(() => {
    const storedUser = initializeAuth();
    if (!storedUser) {
      router.replace('/');
      return;
    }
    setUser(storedUser);

    const fetchData = async () => {
      try {
        const profile = await api.getMe();
        setUserProfile(profile);

        const runData = await api.getSyncRun(runId);
        setRun(runData);

        // Start streaming if queued or running
        if (['queued', 'running', 'pending'].includes(runData.status)) {
          startStreaming();
        }
      } catch (error) {
        if ((error as Error).message.includes('not allowed')) {
          setAccessDenied(true);
          return;
        }
        console.error('Failed to fetch data:', error);
        alert('加载记录失败');
        router.replace('/sync-runs');
      } finally {
        setLoading(false);
      }
    };

    fetchData();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [router, runId]);

  const startStreaming = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setIsStreaming(true);
    const streamUrl = api.getSyncRunStreamUrl(runId);
    const eventSource = new EventSource(streamUrl);
    eventSourceRef.current = eventSource;

    eventSource.addEventListener('status', (event) => {
      const data = JSON.parse(event.data);
      setRun(prev => prev ? { ...prev, ...data } : null);
    });

    eventSource.addEventListener('complete', (event) => {
      const data = JSON.parse(event.data);
      setRun(prev => prev ? { ...prev, ...data } : null);
      setIsStreaming(false);
      eventSource.close();
    });

    eventSource.addEventListener('error', (event) => {
      console.error('SSE error:', event);
      setIsStreaming(false);
      eventSource.close();
    });

    eventSource.onerror = () => {
      setIsStreaming(false);
      eventSource.close();
    };
  };

  const handleCancel = async () => {
    if (!confirm('确定要取消此同步任务吗？')) return;
    
    try {
      const updatedRun = await api.cancelSyncRun(runId);
      setRun(updatedRun);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        setIsStreaming(false);
      }
    } catch (error) {
      alert('取消失败：' + (error as Error).message);
    }
  };

  const openFileModal = async (type: FileModalType) => {
    if (!type) return;
    
    setModalType(type);
    setModalLoading(true);
    setModalFiles([]);
    
    try {
      const statusMap: Record<string, FileStatus> = {
        downloaded: 'downloaded',
        skipped: 'skipped',
        failed: 'failed',
      };
      const result = await api.getSyncRunFiles(runId, statusMap[type]);
      setModalFiles(result.items);
    } catch (error) {
      console.error('Failed to load files:', error);
    } finally {
      setModalLoading(false);
    }
  };

  const closeFileModal = () => {
    setModalType(null);
    setModalFiles([]);
  };

  const getModalTitle = () => {
    switch (modalType) {
      case 'downloaded': return '已下载文件';
      case 'skipped': return '已跳过文件';
      case 'failed': return '失败文件';
      default: return '';
    }
  };

  const getStatusBadge = (run: SyncRun) => {
    const classes = `status-${run.status}`;
    const labels: Record<string, string> = {
      queued: '排队中',
      pending: '等待中',
      running: '运行中',
      completed: '已完成',
      failed: '失败',
      auth_required: '需要授权',
      cancelled: '已取消',
    };
    const baseLabel = labels[run.status] || run.status;
    const label = run.status === 'queued' && run.queue_position
      ? `${baseLabel} #${run.queue_position}`
      : baseLabel;
    return (
      <span className={`px-3 py-1.5 rounded-lg text-sm font-medium ${classes}`}>
        {label}
      </span>
    );
  };

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return '-';
    if (seconds < 60) return `${Math.round(seconds)} 秒`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    if (minutes < 60) return `${minutes} 分 ${remainingSeconds} 秒`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours} 小时 ${remainingMinutes} 分`;
  };

  if (!user || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-pulse-slow text-dark-muted">加载中...</div>
      </div>
    );
  }

  if (accessDenied) {
    return <AccessDenied />;
  }

  if (!run) return null;

  const isActive = run.status === 'queued' || run.status === 'running' || run.status === 'pending';

  return (
    <Shell user={user} userProfile={userProfile}>
      <div className="max-w-3xl mx-auto space-y-6 animate-slide-up">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <button
              onClick={() => router.back()}
              className="flex items-center gap-2 text-dark-muted hover:text-dark-text transition-colors mb-4"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              返回
            </button>
            <h1 className="text-2xl font-bold text-dark-text">同步执行详情</h1>
            <p className="text-dark-muted mt-1">
              {run.config_name || `配置 #${run.config_id}`}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {getStatusBadge(run)}
            {isActive && (
              <button onClick={handleCancel} className="btn btn-danger">
                取消同步
              </button>
            )}
          </div>
        </div>

        {/* Progress card (for active runs) */}
        {isActive && (
          <div className="card p-6">
            <div className="mb-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-dark-muted">同步进度</span>
                <span className="text-sm font-medium text-dark-text">
                  {Math.round(run.progress_percent)}%
                </span>
              </div>
              <div className="progress-bar">
                <div
                  className="progress-bar-fill"
                  style={{ width: `${run.progress_percent}%` }}
                />
              </div>
            </div>

            {run.status === 'queued' && (
              <div className="flex items-center gap-2 text-sm text-dark-muted">
                排队中{run.queue_position ? `，当前第 ${run.queue_position} 位` : ''}
              </div>
            )}
            {run.status !== 'queued' && run.current_stage && (
              <div className="flex items-center gap-2 text-sm">
                <div className="w-2 h-2 rounded-full bg-feishu-blue animate-pulse" />
                <span className="text-dark-muted">
                  {run.current_stage === 'discovering' && '发现文件中...'}
                  {run.current_stage === 'downloading' && '下载中...'}
                  {run.current_stage === 'planned' && '准备下载...'}
                  {run.current_stage === 'starting' && '启动中...'}
                  {!['discovering', 'downloading', 'planned', 'starting'].includes(run.current_stage) && run.current_stage}
                </span>
                {run.current_file && (
                  <span className="text-dark-text truncate max-w-md">
                    {run.current_file}
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Stats grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="card p-4">
            <div className="text-sm text-dark-muted mb-1">发现文件</div>
            <div className="text-2xl font-bold text-dark-text">{run.total_files}</div>
          </div>
          <button
            onClick={() => run.downloaded > 0 && openFileModal('downloaded')}
            disabled={run.downloaded === 0}
            className={`card p-4 text-left transition-all ${
              run.downloaded > 0 ? 'hover:ring-2 hover:ring-feishu-green/50 cursor-pointer' : ''
            }`}
          >
            <div className="text-sm text-dark-muted mb-1">已下载</div>
            <div className="text-2xl font-bold text-feishu-green flex items-center gap-2">
              {run.downloaded}
              {run.downloaded > 0 && (
                <svg className="w-4 h-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              )}
            </div>
          </button>
          <button
            onClick={() => run.skipped > 0 && openFileModal('skipped')}
            disabled={run.skipped === 0}
            className={`card p-4 text-left transition-all ${
              run.skipped > 0 ? 'hover:ring-2 hover:ring-dark-muted/50 cursor-pointer' : ''
            }`}
          >
            <div className="text-sm text-dark-muted mb-1">已跳过</div>
            <div className="text-2xl font-bold text-dark-muted flex items-center gap-2">
              {run.skipped}
              {run.skipped > 0 && (
                <svg className="w-4 h-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              )}
            </div>
          </button>
          <button
            onClick={() => run.errors > 0 && openFileModal('failed')}
            disabled={run.errors === 0}
            className={`card p-4 text-left transition-all ${
              run.errors > 0 ? 'hover:ring-2 hover:ring-feishu-red/50 cursor-pointer' : ''
            }`}
          >
            <div className="text-sm text-dark-muted mb-1">错误</div>
            <div className={`text-2xl font-bold flex items-center gap-2 ${run.errors > 0 ? 'text-feishu-red' : 'text-dark-muted'}`}>
              {run.errors}
              {run.errors > 0 && (
                <svg className="w-4 h-4 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              )}
            </div>
          </button>
        </div>

        {/* Details card */}
        <div className="card">
          <div className="p-5 border-b border-dark-border">
            <h2 className="font-medium text-dark-text">执行详情</h2>
          </div>
          <div className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-sm text-dark-muted mb-1">配置 ID</div>
                <div className="text-dark-text">{run.config_id}</div>
              </div>
              <div>
                <div className="text-sm text-dark-muted mb-1">执行 ID</div>
                <div className="text-dark-text">{run.id}</div>
              </div>
              <div>
                <div className="text-sm text-dark-muted mb-1">创建时间</div>
                <div className="text-dark-text">
                  {new Date(run.created_at).toLocaleString('zh-CN')}
                </div>
              </div>
              <div>
                <div className="text-sm text-dark-muted mb-1">开始时间</div>
                <div className="text-dark-text">
                  {run.started_at
                    ? new Date(run.started_at).toLocaleString('zh-CN')
                    : '-'}
                </div>
              </div>
              <div>
                <div className="text-sm text-dark-muted mb-1">完成时间</div>
                <div className="text-dark-text">
                  {run.finished_at
                    ? new Date(run.finished_at).toLocaleString('zh-CN')
                    : '-'}
                </div>
              </div>
              <div>
                <div className="text-sm text-dark-muted mb-1">耗时</div>
                <div className="text-dark-text">
                  {formatDuration(run.duration_seconds)}
                </div>
              </div>
            </div>

            {run.error_message && (
              <div className="mt-4 p-4 bg-feishu-red/10 border border-feishu-red/30 rounded-lg">
                <div className="text-sm font-medium text-feishu-red mb-1">错误信息</div>
                <div className="text-sm text-dark-text font-mono whitespace-pre-wrap">
                  {run.error_message}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Streaming indicator */}
        {isStreaming && (
          <div className="text-center text-sm text-dark-muted">
            <span className="inline-flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-feishu-green animate-pulse" />
              实时更新中...
            </span>
          </div>
        )}
      </div>

      {/* File list modal */}
      {modalType && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-dark-card rounded-2xl shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            {/* Modal header */}
            <div className="flex items-center justify-between p-5 border-b border-dark-border">
              <h3 className="text-lg font-medium text-dark-text">{getModalTitle()}</h3>
              <button
                onClick={closeFileModal}
                className="p-2 rounded-lg hover:bg-dark-border/50 transition-colors"
              >
                <svg className="w-5 h-5 text-dark-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal content */}
            <div className="flex-1 overflow-y-auto p-5">
              {modalLoading ? (
                <div className="text-center py-8 text-dark-muted animate-pulse-slow">
                  加载中...
                </div>
              ) : modalFiles.length === 0 ? (
                <div className="text-center py-8 text-dark-muted">
                  暂无记录
                </div>
              ) : (
                <div className="space-y-3">
                  {modalFiles.map((file) => (
                    <div
                      key={file.id}
                      className="p-4 bg-dark-bg rounded-lg border border-dark-border"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-dark-text truncate">
                            {file.file_name}
                          </div>
                          {file.file_path && (
                            <div className="text-sm text-dark-muted mt-1 truncate" title={file.file_path}>
                              {file.file_path}
                            </div>
                          )}
                          {file.reason && (
                            <div className={`text-sm mt-2 p-2 rounded ${
                              modalType === 'failed'
                                ? 'bg-feishu-red/10 text-feishu-red'
                                : 'bg-dark-border/50 text-dark-muted'
                            }`}>
                              {file.reason}
                            </div>
                          )}
                        </div>
                        {file.file_type && (
                          <span className="px-2 py-1 text-xs bg-dark-border rounded text-dark-muted shrink-0">
                            {file.file_type}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Modal footer */}
            <div className="p-5 border-t border-dark-border">
              <div className="text-sm text-dark-muted">
                共 {modalFiles.length} 条记录
              </div>
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}
