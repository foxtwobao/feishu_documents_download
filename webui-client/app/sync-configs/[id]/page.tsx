'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { initializeAuth, SessionUser } from '@/lib/auth';
import api, { SyncConfig, User } from '@/lib/api';
import Shell from '@/components/Shell';
import AccessDenied from '@/components/AccessDenied';

export default function EditSyncConfigPage() {
  const router = useRouter();
  const params = useParams();
  const configId = parseInt(params.id as string);
  
  const [user, setUser] = useState<SessionUser | null>(null);
  const [userProfile, setUserProfile] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<SyncConfig | null>(null);

  // Form state
  const [name, setName] = useState('');
  const [syncMode, setSyncMode] = useState<'incremental' | 'full'>('incremental');
  const [limit, setLimit] = useState(0);
  const [scheduleType, setScheduleType] = useState<'manual' | 'cron' | 'interval'>('manual');
  const [scheduleCron, setScheduleCron] = useState('0 3 * * *');
  const [scheduleIntervalHours, setScheduleIntervalHours] = useState(6);
  const [enabled, setEnabled] = useState(true);

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

        const configData = await api.getSyncConfig(configId);
        setConfig(configData);
        
        // Initialize form state
        setName(configData.name);
        setSyncMode(configData.sync_mode);
        setLimit(configData.limit);
        setScheduleType(configData.schedule_type);
        setScheduleCron(configData.schedule_cron || '0 3 * * *');
        setScheduleIntervalHours(configData.schedule_interval_hours || 6);
        setEnabled(configData.enabled);
      } catch (error) {
        if ((error as Error).message.includes('not allowed')) {
          setAccessDenied(true);
          return;
        }
        console.error('Failed to fetch data:', error);
        alert('加载配置失败');
        router.replace('/sync-configs');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [router, configId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!name.trim()) {
      alert('请输入配置名称');
      return;
    }

    setSaving(true);
    try {
      await api.updateSyncConfig(configId, {
        name: name.trim(),
        sync_mode: syncMode,
        limit,
        schedule_type: scheduleType,
        schedule_cron: scheduleType === 'cron' ? scheduleCron : undefined,
        schedule_interval_hours: scheduleType === 'interval' ? scheduleIntervalHours : undefined,
        enabled,
      });

      router.push('/sync-configs');
    } catch (error) {
      alert('保存失败：' + (error as Error).message);
    } finally {
      setSaving(false);
    }
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

  if (!config) return null;

  return (
    <Shell user={user} userProfile={userProfile}>
      <div className="max-w-2xl mx-auto animate-slide-up">
        {/* Header */}
        <div className="mb-6">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-2 text-dark-muted hover:text-dark-text transition-colors mb-4"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            返回
          </button>
          <h1 className="text-2xl font-bold text-dark-text">编辑同步配置</h1>
          <p className="text-dark-muted mt-1">
            {config.sync_type === 'my_space' ? '我的空间' : config.wiki_space_name || '知识库'}
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="card p-6 space-y-6">
          {/* Enabled toggle */}
          <div className="flex items-center justify-between p-4 bg-dark-bg rounded-lg">
            <div>
              <div className="font-medium text-dark-text">启用配置</div>
              <div className="text-sm text-dark-muted">关闭后定时任务将不会执行</div>
            </div>
            <button
              type="button"
              onClick={() => setEnabled(!enabled)}
              className={`relative w-12 h-6 rounded-full transition-colors ${
                enabled ? 'bg-feishu-blue' : 'bg-dark-border'
              }`}
            >
              <div className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
                enabled ? 'translate-x-6' : 'translate-x-0.5'
              }`} />
            </button>
          </div>

          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-dark-text mb-2">
              配置名称 *
            </label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="例如：每日同步我的空间"
              className="input"
              required
            />
          </div>

          {/* Sync Mode */}
          <div>
            <label className="block text-sm font-medium text-dark-text mb-2">
              同步方式
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setSyncMode('incremental')}
                className={`p-3 rounded-lg border transition-all text-left ${
                  syncMode === 'incremental'
                    ? 'border-feishu-blue bg-feishu-blue/10'
                    : 'border-dark-border hover:border-dark-muted'
                }`}
              >
                <div className="font-medium text-dark-text text-sm">增量同步</div>
                <div className="text-xs text-dark-muted">只同步新增和修改的文件</div>
              </button>
              <button
                type="button"
                onClick={() => setSyncMode('full')}
                className={`p-3 rounded-lg border transition-all text-left ${
                  syncMode === 'full'
                    ? 'border-feishu-orange bg-feishu-orange/10'
                    : 'border-dark-border hover:border-dark-muted'
                }`}
              >
                <div className="font-medium text-dark-text text-sm">全量同步</div>
                <div className="text-xs text-dark-muted">重新下载所有文件</div>
              </button>
            </div>
          </div>

          {/* Limit */}
          <div>
            <label className="block text-sm font-medium text-dark-text mb-2">
              单次同步文件数限制
            </label>
            <input
              type="number"
              value={limit}
              onChange={e => setLimit(parseInt(e.target.value) || 0)}
              min="0"
              placeholder="0 表示不限制"
              className="input"
            />
          </div>

          {/* Schedule */}
          <div>
            <label className="block text-sm font-medium text-dark-text mb-2">
              调度方式
            </label>
            <div className="grid grid-cols-3 gap-3 mb-3">
              <button
                type="button"
                onClick={() => setScheduleType('manual')}
                className={`p-3 rounded-lg border transition-all ${
                  scheduleType === 'manual'
                    ? 'border-feishu-blue bg-feishu-blue/10'
                    : 'border-dark-border hover:border-dark-muted'
                }`}
              >
                <div className="font-medium text-dark-text text-sm">手动触发</div>
              </button>
              <button
                type="button"
                onClick={() => setScheduleType('interval')}
                className={`p-3 rounded-lg border transition-all ${
                  scheduleType === 'interval'
                    ? 'border-feishu-blue bg-feishu-blue/10'
                    : 'border-dark-border hover:border-dark-muted'
                }`}
              >
                <div className="font-medium text-dark-text text-sm">固定间隔</div>
              </button>
              <button
                type="button"
                onClick={() => setScheduleType('cron')}
                className={`p-3 rounded-lg border transition-all ${
                  scheduleType === 'cron'
                    ? 'border-feishu-blue bg-feishu-blue/10'
                    : 'border-dark-border hover:border-dark-muted'
                }`}
              >
                <div className="font-medium text-dark-text text-sm">Cron 表达式</div>
              </button>
            </div>

            {scheduleType === 'interval' && (
              <div>
                <label className="block text-sm text-dark-muted mb-1">间隔小时数</label>
                <input
                  type="number"
                  value={scheduleIntervalHours}
                  onChange={e => setScheduleIntervalHours(parseInt(e.target.value) || 1)}
                  min="1"
                  className="input"
                />
              </div>
            )}

            {scheduleType === 'cron' && (
              <div>
                <label className="block text-sm text-dark-muted mb-1">Cron 表达式</label>
                <input
                  type="text"
                  value={scheduleCron}
                  onChange={e => setScheduleCron(e.target.value)}
                  placeholder="0 3 * * *"
                  className="input"
                />
                <p className="text-xs text-dark-muted mt-1">例如：0 3 * * * 表示每天凌晨3点执行</p>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-dark-border">
            <button
              type="button"
              onClick={() => router.back()}
              className="btn btn-secondary"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving}
              className="btn btn-primary"
            >
              {saving ? '保存中...' : '保存更改'}
            </button>
          </div>
        </form>
      </div>
    </Shell>
  );
}
