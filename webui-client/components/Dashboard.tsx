'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { SessionUser } from '@/lib/auth';
import api, { SyncConfig, SyncRun, User } from '@/lib/api';

interface DashboardProps {
  user: SessionUser;
  userProfile: User | null;
}

export default function Dashboard({ user, userProfile }: DashboardProps) {
  const [configs, setConfigs] = useState<SyncConfig[]>([]);
  const [recentRuns, setRecentRuns] = useState<SyncRun[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [configsData, runsData] = await Promise.all([
          api.listSyncConfigs(),
          api.listSyncRuns({ page_size: 5 }),
        ]);
        setConfigs(configsData);
        setRecentRuns(runsData.items);
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'text-feishu-blue';
      case 'completed': return 'text-feishu-green';
      case 'failed': return 'text-feishu-red';
      case 'auth_required': return 'text-feishu-orange';
      default: return 'text-dark-muted';
    }
  };

  const getStatusText = (status: string) => {
    switch (status) {
      case 'pending': return '等待中';
      case 'running': return '运行中';
      case 'completed': return '已完成';
      case 'failed': return '失败';
      case 'auth_required': return '需要授权';
      case 'cancelled': return '已取消';
      default: return status;
    }
  };

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Welcome header */}
      <div className="card p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-dark-text mb-1">
              欢迎回来，{user.display_name || '用户'}
            </h1>
            <p className="text-dark-muted">
              {userProfile?.storage_root 
                ? `存储路径: ${userProfile.storage_root}` 
                : '管理你的飞书文档同步任务'}
            </p>
          </div>
          <Link
            href="/sync-configs/new"
            className="btn btn-primary flex items-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            新建同步配置
          </Link>
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card p-5">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-feishu-blue/20 flex items-center justify-center">
              <svg className="w-6 h-6 text-feishu-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              </svg>
            </div>
            <div>
              <div className="text-2xl font-bold text-dark-text">{configs.length}</div>
              <div className="text-sm text-dark-muted">同步配置</div>
            </div>
          </div>
        </div>

        <div className="card p-5">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-feishu-green/20 flex items-center justify-center">
              <svg className="w-6 h-6 text-feishu-green" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <div className="text-2xl font-bold text-dark-text">
                {recentRuns.filter(r => r.status === 'completed').length}
              </div>
              <div className="text-sm text-dark-muted">近期完成</div>
            </div>
          </div>
        </div>

        <div className="card p-5">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-feishu-orange/20 flex items-center justify-center">
              <svg className="w-6 h-6 text-feishu-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <div className="text-2xl font-bold text-dark-text">
                {configs.filter(c => c.schedule_type !== 'manual' && c.enabled).length}
              </div>
              <div className="text-sm text-dark-muted">定时任务</div>
            </div>
          </div>
        </div>
      </div>

      {/* Recent sync runs */}
      <div className="card">
        <div className="p-5 border-b border-dark-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-dark-text">最近同步记录</h2>
          <Link href="/sync-runs" className="text-sm text-feishu-blue hover:underline">
            查看全部
          </Link>
        </div>
        
        {loading ? (
          <div className="p-8 text-center text-dark-muted animate-pulse-slow">
            加载中...
          </div>
        ) : recentRuns.length === 0 ? (
          <div className="p-8 text-center text-dark-muted">
            暂无同步记录
          </div>
        ) : (
          <div className="divide-y divide-dark-border">
            {recentRuns.map((run) => (
              <Link
                key={run.id}
                href={`/sync-runs/${run.id}`}
                className="flex items-center justify-between p-4 hover:bg-dark-border/30 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <div className={`w-2 h-2 rounded-full ${
                    run.status === 'running' ? 'bg-feishu-blue animate-pulse' :
                    run.status === 'completed' ? 'bg-feishu-green' :
                    run.status === 'failed' ? 'bg-feishu-red' :
                    'bg-dark-muted'
                  }`} />
                  <div>
                    <div className="text-sm font-medium text-dark-text">
                      {run.config_name || `配置 #${run.config_id}`}
                    </div>
                    <div className="text-xs text-dark-muted">
                      {new Date(run.created_at).toLocaleString('zh-CN')}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className={`text-sm font-medium ${getStatusColor(run.status)}`}>
                      {getStatusText(run.status)}
                    </div>
                    {run.status === 'completed' && (
                      <div className="text-xs text-dark-muted">
                        {run.downloaded} 已下载 / {run.skipped} 跳过
                      </div>
                    )}
                  </div>
                  <svg className="w-4 h-4 text-dark-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Quick actions / Sync configs */}
      <div className="card">
        <div className="p-5 border-b border-dark-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-dark-text">同步配置</h2>
          <Link href="/sync-configs" className="text-sm text-feishu-blue hover:underline">
            管理配置
          </Link>
        </div>
        
        {loading ? (
          <div className="p-8 text-center text-dark-muted animate-pulse-slow">
            加载中...
          </div>
        ) : configs.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-dark-muted mb-4">还没有同步配置，点击下方按钮创建第一个</p>
            <Link href="/sync-configs/new" className="btn btn-primary">
              创建同步配置
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-dark-border">
            {configs.slice(0, 3).map((config) => (
              <div
                key={config.id}
                className="flex items-center justify-between p-4"
              >
                <div className="flex items-center gap-4">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                    config.sync_type === 'my_space' 
                      ? 'bg-feishu-blue/20 text-feishu-blue'
                      : 'bg-feishu-green/20 text-feishu-green'
                  }`}>
                    {config.sync_type === 'my_space' ? (
                      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                      </svg>
                    ) : (
                      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                      </svg>
                    )}
                  </div>
                  <div>
                    <div className="text-sm font-medium text-dark-text">{config.name}</div>
                    <div className="text-xs text-dark-muted">
                      {config.sync_type === 'my_space' ? '我的空间' : config.wiki_space_name || '知识库'}
                      {' · '}
                      {config.schedule_type === 'manual' ? '手动触发' : 
                       config.schedule_type === 'cron' ? config.schedule_cron :
                       `每 ${config.schedule_interval_hours} 小时`}
                    </div>
                  </div>
                </div>
                <button
                  onClick={async () => {
                    try {
                      const result = await api.triggerSync(config.id);
                      alert(`同步已触发，任务 ID: ${result.sync_run_id}`);
                    } catch (error) {
                      alert('触发同步失败：' + (error as Error).message);
                    }
                  }}
                  disabled={!config.enabled}
                  className="btn btn-secondary text-sm"
                >
                  立即同步
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
