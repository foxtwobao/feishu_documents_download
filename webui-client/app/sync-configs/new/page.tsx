'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { initializeAuth, SessionUser } from '@/lib/auth';
import api, { User, WikiSpace } from '@/lib/api';
import Shell from '@/components/Shell';
import AccessDenied from '@/components/AccessDenied';

export default function NewSyncConfigPage() {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [userProfile, setUserProfile] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [wikiSpaces, setWikiSpaces] = useState<WikiSpace[]>([]);
  const [loadingWikiSpaces, setLoadingWikiSpaces] = useState(false);
  const [wikiBlocked, setWikiBlocked] = useState(false);

  // Form state
  const [name, setName] = useState('');
  const [syncType, setSyncType] = useState<'my_space' | 'wiki'>('my_space');
  const [wikiSpaceId, setWikiSpaceId] = useState('');
  const [syncMode, setSyncMode] = useState<'incremental' | 'full'>('incremental');
  const [limit, setLimit] = useState(0);
  const [scheduleType, setScheduleType] = useState<'manual' | 'cron' | 'interval'>('manual');
  const [scheduleCron, setScheduleCron] = useState('0 3 * * *');
  const [scheduleIntervalHours, setScheduleIntervalHours] = useState(6);

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
      })
      .finally(() => setLoading(false));
  }, [router]);

  const wikiAllowed = userProfile?.wiki_allowed ?? false;

  useEffect(() => {
    if (!wikiAllowed && syncType === 'wiki') {
      setSyncType('my_space');
    }
  }, [wikiAllowed, syncType]);

  useEffect(() => {
    if (!wikiAllowed || syncType !== 'wiki' || wikiSpaces.length > 0 || loadingWikiSpaces) {
      return;
    }
    setLoadingWikiSpaces(true);
    setWikiBlocked(false);
    api.listWikiSpaces()
      .then(spaces => setWikiSpaces(spaces))
      .catch((error) => {
        console.error(error);
        setWikiBlocked(true);
      })
      .finally(() => setLoadingWikiSpaces(false));
  }, [wikiAllowed, syncType, wikiSpaces.length, loadingWikiSpaces]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!name.trim()) {
      alert('请输入配置名称');
      return;
    }

    if (syncType === 'wiki' && !wikiSpaceId) {
      alert('请选择知识库');
      return;
    }

    setSaving(true);
    try {
      const selectedWiki = wikiSpaces.find(w => w.space_id === wikiSpaceId);
      
      await api.createSyncConfig({
        name: name.trim(),
        sync_type: syncType,
        wiki_space_id: syncType === 'wiki' ? wikiSpaceId : undefined,
        wiki_space_name: syncType === 'wiki' ? selectedWiki?.name : undefined,
        sync_mode: syncMode,
        limit,
        schedule_type: scheduleType,
        schedule_cron: scheduleType === 'cron' ? scheduleCron : undefined,
        schedule_interval_hours: scheduleType === 'interval' ? scheduleIntervalHours : undefined,
        enabled: true,
      });

      router.push('/sync-configs');
    } catch (error) {
      alert('创建失败：' + (error as Error).message);
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
          <h1 className="text-2xl font-bold text-dark-text">新建同步配置</h1>
          <p className="text-dark-muted mt-1">配置自动同步飞书文档到本地</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="card p-6 space-y-6">
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

          {/* Sync Type */}
          <div>
            <label className="block text-sm font-medium text-dark-text mb-2">
              同步类型 *
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setSyncType('my_space')}
                className={`p-4 rounded-lg border-2 transition-all ${
                  syncType === 'my_space'
                    ? 'border-feishu-blue bg-feishu-blue/10'
                    : 'border-dark-border hover:border-dark-muted'
                }`}
              >
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-2 ${
                  syncType === 'my_space' ? 'bg-feishu-blue/20 text-feishu-blue' : 'bg-dark-border text-dark-muted'
                }`}>
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
                  </svg>
                </div>
                <div className="text-left">
                  <div className="font-medium text-dark-text">我的空间</div>
                  <div className="text-xs text-dark-muted">同步个人云空间的所有文档</div>
                </div>
              </button>
              
              <button
                type="button"
                onClick={() => wikiAllowed && setSyncType('wiki')}
                disabled={!wikiAllowed}
                className={`p-4 rounded-lg border-2 transition-all ${
                  syncType === 'wiki'
                    ? 'border-feishu-green bg-feishu-green/10'
                    : wikiAllowed
                    ? 'border-dark-border hover:border-dark-muted'
                    : 'border-dark-border opacity-50 cursor-not-allowed'
                }`}
              >
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-2 ${
                  syncType === 'wiki' ? 'bg-feishu-green/20 text-feishu-green' : 'bg-dark-border text-dark-muted'
                }`}>
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                  </svg>
                </div>
                <div className="text-left">
                  <div className="font-medium text-dark-text">知识库</div>
                  <div className="text-xs text-dark-muted">
                    {wikiAllowed ? '同步指定知识库的所有文档' : '当前账号未授权知识库同步'}
                  </div>
                </div>
              </button>
            </div>
          </div>

          {/* Wiki Space Selection */}
          {syncType === 'wiki' && (
            <div>
              <label className="block text-sm font-medium text-dark-text mb-2">
                选择知识库 *
              </label>
              {!wikiAllowed ? (
                <div className="text-dark-muted text-sm">当前账号未授权知识库同步</div>
              ) : loadingWikiSpaces ? (
                <div className="text-dark-muted text-sm">加载知识库列表...</div>
              ) : wikiBlocked ? (
                <div className="text-dark-muted text-sm">未开启知识库同步权限</div>
              ) : wikiSpaces.length === 0 ? (
                <div className="text-dark-muted text-sm">未找到可访问的知识库</div>
              ) : (
                <select
                  value={wikiSpaceId}
                  onChange={e => setWikiSpaceId(e.target.value)}
                  className="select"
                  required
                >
                  <option value="">请选择知识库</option>
                  {wikiSpaces.map(space => (
                    <option key={space.space_id} value={space.space_id}>
                      {space.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

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
            <p className="text-xs text-dark-muted mt-1">设置为 0 表示不限制同步文件数量</p>
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
              {saving ? '创建中...' : '创建配置'}
            </button>
          </div>
        </form>
      </div>
    </Shell>
  );
}
