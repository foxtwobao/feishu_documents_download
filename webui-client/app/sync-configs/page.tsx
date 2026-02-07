'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { initializeAuth, SessionUser } from '@/lib/auth';
import api, { SyncConfig, User } from '@/lib/api';
import Shell from '@/components/Shell';
import AccessDenied from '@/components/AccessDenied';

export default function SyncConfigsPage() {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [userProfile, setUserProfile] = useState<User | null>(null);
  const [configs, setConfigs] = useState<SyncConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [syncingId, setSyncingId] = useState<number | null>(null);  // 刚触发同步的配置 ID
  const [activeStatusByConfigId, setActiveStatusByConfigId] = useState<Record<number, string>>({});

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
      } catch (error) {
        if ((error as Error).message.includes('not allowed')) {
          setAccessDenied(true);
          setLoading(false);
          return;
        }
        console.error('Failed to fetch profile:', error);
      }

      try {
        const [configsData, runsData] = await Promise.all([
          api.listSyncConfigs(),
          api.listSyncRuns({ page_size: 50 }),  // 获取最近的同步任务
        ]);
        setConfigs(configsData);

        const activeStatuses: Record<number, string> = {};
        runsData.items.forEach((run) => {
          if (!['queued', 'pending', 'running'].includes(run.status)) {
            return;
          }
          if (activeStatuses[run.config_id] === undefined) {
            activeStatuses[run.config_id] = run.status;
          }
        });
        setActiveStatusByConfigId(activeStatuses);
      } catch (error) {
        console.error('Failed to fetch data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [router]);

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除此同步配置吗？')) return;
    
    try {
      await api.deleteSyncConfig(id);
      setConfigs(configs.filter(c => c.id !== id));
    } catch (error) {
      alert('删除失败：' + (error as Error).message);
    }
  };

  const handleTriggerSync = async (id: number) => {
    setSyncingId(id);
    try {
      const result = await api.triggerSync(id);
      router.push(`/sync-runs/${result.sync_run_id}`);
    } catch (error) {
      alert('触发同步失败：' + (error as Error).message);
      setSyncingId(null);
    }
  };

  if (!user) return null;
  if (accessDenied) {
    return <AccessDenied />;
  }

  return (
    <Shell user={user} userProfile={userProfile}>
      <div className="space-y-6 animate-slide-up">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-dark-text">同步配置</h1>
            <p className="text-dark-muted mt-1">管理你的飞书文档同步任务</p>
          </div>
          <Link href="/sync-configs/new" className="btn btn-primary flex items-center gap-2">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            新建配置
          </Link>
        </div>

        {/* Configs list */}
        {loading ? (
          <div className="card p-8 text-center text-dark-muted animate-pulse-slow">
            加载中...
          </div>
        ) : configs.length === 0 ? (
          <div className="card p-12 text-center">
            <div className="w-16 h-16 mx-auto mb-4 bg-dark-border rounded-2xl flex items-center justify-center">
              <svg className="w-8 h-8 text-dark-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              </svg>
            </div>
            <h3 className="text-lg font-medium text-dark-text mb-2">还没有同步配置</h3>
            <p className="text-dark-muted mb-6">创建第一个同步配置，开始自动同步飞书文档</p>
            <Link href="/sync-configs/new" className="btn btn-primary">
              创建同步配置
            </Link>
          </div>
        ) : (
          <div className="grid gap-4">
            {configs.map((config) => (
              <div key={config.id} className="card card-hover p-5">
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-4">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                      config.sync_type === 'my_space'
                        ? 'bg-feishu-blue/20 text-feishu-blue'
                        : 'bg-feishu-green/20 text-feishu-green'
                    }`}>
                      {config.sync_type === 'my_space' ? (
                        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                        </svg>
                      ) : (
                        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                        </svg>
                      )}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-medium text-dark-text">{config.name}</h3>
                        {!config.enabled && (
                          <span className="px-2 py-0.5 text-xs bg-dark-border rounded text-dark-muted">
                            已禁用
                          </span>
                        )}
                      </div>
                      <div className="text-sm text-dark-muted mt-1">
                        {config.sync_type === 'my_space' ? '我的空间' : config.wiki_space_name || '知识库'}
                        {' · '}
                        {config.sync_mode === 'incremental' ? '增量同步' : '全量同步'}
                        {config.limit > 0 && ` · 限制 ${config.limit} 个文件`}
                      </div>
                      <div className="flex items-center gap-4 mt-2 text-xs text-dark-muted">
                        <span className="flex items-center gap-1">
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          {config.schedule_type === 'manual' 
                            ? '手动触发' 
                            : config.schedule_type === 'cron'
                            ? `Cron: ${config.schedule_cron}`
                            : `每 ${config.schedule_interval_hours} 小时`}
                        </span>
                        {config.last_run_at && (
                          <span>
                            上次运行: {new Date(config.last_run_at).toLocaleString('zh-CN')}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    {(() => {
                      const activeStatus = activeStatusByConfigId[config.id];
                      const isRunning = Boolean(activeStatus) || syncingId === config.id;
                      const statusLabel = activeStatus === 'queued'
                        ? '排队中'
                        : activeStatus === 'pending'
                        ? '等待中'
                        : '运行中';
                      return (
                        <button
                          onClick={() => handleTriggerSync(config.id)}
                          disabled={!config.enabled || isRunning}
                          className="btn btn-secondary text-sm min-w-[88px] flex items-center justify-center gap-2"
                        >
                          {isRunning ? (
                            <>
                              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                              </svg>
                              {statusLabel}
                            </>
                          ) : (
                            '立即同步'
                          )}
                        </button>
                      );
                    })()}
                    <Link
                      href={`/sync-configs/${config.id}`}
                      className="p-2 rounded-lg hover:bg-dark-border/50 transition-colors"
                    >
                      <svg className="w-5 h-5 text-dark-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                      </svg>
                    </Link>
                    <button
                      onClick={() => handleDelete(config.id)}
                      className="p-2 rounded-lg hover:bg-feishu-red/10 transition-colors"
                    >
                      <svg className="w-5 h-5 text-feishu-red" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Shell>
  );
}
