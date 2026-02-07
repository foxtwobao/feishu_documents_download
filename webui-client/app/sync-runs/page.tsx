'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { initializeAuth, SessionUser } from '@/lib/auth';
import api, { SyncRun, User } from '@/lib/api';
import Shell from '@/components/Shell';
import AccessDenied from '@/components/AccessDenied';

export default function SyncRunsPage() {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [userProfile, setUserProfile] = useState<User | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 10;

  useEffect(() => {
    const storedUser = initializeAuth();
    if (!storedUser) {
      router.replace('/');
      return;
    }
    setUser(storedUser);
    
    api.getMe()
      .then(profile => setUserProfile(profile))
      .catch((error) => {
        if ((error as Error).message.includes('not allowed')) {
          setAccessDenied(true);
        } else {
          console.error(error);
        }
      });
  }, [router]);

  useEffect(() => {
    if (!user) return;
    
    const fetchRuns = async () => {
      setLoading(true);
      try {
        if (accessDenied) {
          return;
        }
        const data = await api.listSyncRuns({ page, page_size: pageSize });
        setRuns(data.items);
        setTotal(data.total);
      } catch (error) {
        console.error('Failed to fetch runs:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchRuns();
  }, [user, page]);

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
      <span className={`px-2 py-1 rounded-md text-xs font-medium ${classes}`}>
        {label}
      </span>
    );
  };

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return '-';
    if (seconds < 60) return `${Math.round(seconds)}秒`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    return `${minutes}分${remainingSeconds}秒`;
  };

  const totalPages = Math.ceil(total / pageSize);

  if (!user) return null;
  if (accessDenied) {
    return <AccessDenied />;
  }

  return (
    <Shell user={user} userProfile={userProfile}>
      <div className="space-y-6 animate-slide-up">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-dark-text">同步执行记录</h1>
          <p className="text-dark-muted mt-1">查看同步任务的执行历史和状态</p>
        </div>

        {/* Runs table */}
        <div className="card overflow-hidden">
          {loading && runs.length === 0 ? (
            <div className="p-8 text-center text-dark-muted animate-pulse-slow">
              加载中...
            </div>
          ) : runs.length === 0 ? (
            <div className="p-8 text-center text-dark-muted">
              暂无执行记录
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-dark-bg/50">
                    <tr className="text-left text-sm text-dark-muted">
                      <th className="px-4 py-3 font-medium">配置</th>
                      <th className="px-4 py-3 font-medium">状态</th>
                      <th className="px-4 py-3 font-medium">进度</th>
                      <th className="px-4 py-3 font-medium">开始时间</th>
                      <th className="px-4 py-3 font-medium">耗时</th>
                      <th className="px-4 py-3 font-medium"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-dark-border">
                    {runs.map((run) => (
                      <tr key={run.id} className="hover:bg-dark-border/30 transition-colors">
                        <td className="px-4 py-3">
                          <div className="font-medium text-dark-text">
                            {run.config_name || `配置 #${run.config_id}`}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          {getStatusBadge(run)}
                        </td>
                        <td className="px-4 py-3">
                          {run.status === 'running' ? (
                            <div className="flex items-center gap-2">
                              <div className="w-24 h-2 bg-dark-border rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-feishu-blue transition-all duration-300"
                                  style={{ width: `${run.progress_percent}%` }}
                                />
                              </div>
                              <span className="text-xs text-dark-muted">
                                {Math.round(run.progress_percent)}%
                              </span>
                            </div>
                          ) : run.status === 'queued' ? (
                            <span className="text-sm text-dark-muted">
                              排队中{run.queue_position ? `，第 ${run.queue_position} 位` : ''}
                            </span>
                          ) : run.status === 'completed' ? (
                            <span className="text-sm text-dark-muted">
                              {run.downloaded} 已下载 / {run.skipped} 跳过
                              {run.errors > 0 && ` / ${run.errors} 错误`}
                            </span>
                          ) : run.error_message ? (
                            <span className="text-sm text-feishu-red truncate max-w-xs block">
                              {run.error_message}
                            </span>
                          ) : (
                            <span className="text-sm text-dark-muted">-</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm text-dark-muted">
                          {run.started_at
                            ? new Date(run.started_at).toLocaleString('zh-CN')
                            : new Date(run.created_at).toLocaleString('zh-CN')}
                        </td>
                        <td className="px-4 py-3 text-sm text-dark-muted">
                          {formatDuration(run.duration_seconds)}
                        </td>
                        <td className="px-4 py-3">
                          <Link
                            href={`/sync-runs/${run.id}`}
                            className="text-feishu-blue hover:underline text-sm"
                          >
                            详情
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-dark-border">
                  <div className="text-sm text-dark-muted">
                    共 {total} 条记录
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage(p => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="btn btn-secondary text-sm"
                    >
                      上一页
                    </button>
                    <span className="text-sm text-dark-muted">
                      {page} / {totalPages}
                    </span>
                    <button
                      onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      className="btn btn-secondary text-sm"
                    >
                      下一页
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </Shell>
  );
}
