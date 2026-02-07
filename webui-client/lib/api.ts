/**
 * API client for LarkSync backend
 * 
 * Single-port architecture: frontend and backend are served from the same origin.
 * All API requests use relative paths (same-origin).
 * All backend API endpoints are under /api prefix.
 */

// API base URL - all backend endpoints are under /api
const API_BASE_URL = '/api';

export interface User {
  id: number;
  feishu_user_id: string;
  display_name: string | null;
  avatar_url: string | null;
  email: string | null;
  storage_root: string | null;
  created_at: string;
  last_login_at: string | null;
  token_status: string;
  token_expires_at: string | null;
  refresh_token_expires_at: string | null;
  wiki_allowed: boolean;
}

export interface SyncConfig {
  id: number;
  user_id: number;
  name: string;
  sync_type: 'my_space' | 'wiki';
  wiki_space_id: string | null;
  wiki_space_name: string | null;
  sync_mode: 'incremental' | 'full';
  limit: number;
  schedule_type: 'manual' | 'cron' | 'interval';
  schedule_cron: string | null;
  schedule_interval_hours: number | null;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncRun {
  id: number;
  config_id: number;
  config_name: string | null;
  user_id: number;
  status: 'queued' | 'pending' | 'running' | 'completed' | 'failed' | 'auth_required' | 'cancelled';
  total_files: number;
  total_folders: number;
  downloaded: number;
  skipped: number;
  errors: number;
  current_file: string | null;
  current_stage: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  duration_seconds: number | null;
  progress_percent: number;
  queue_position: number | null;
}

export type FileStatus = 'downloaded' | 'skipped' | 'failed';

export interface SyncFileRecord {
  id: number;
  run_id: number;
  file_name: string;
  file_path: string | null;
  file_type: string | null;
  token: string | null;
  status: FileStatus;
  reason: string | null;
  created_at: string;
}

export interface SyncFileRecordList {
  items: SyncFileRecord[];
  total: number;
}

export interface WikiSpace {
  space_id: string;
  name: string;
  description: string | null;
}

export interface ApiError {
  detail: string;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  // Deprecated: authentication is now handled via cookies set by the server
  setUserId(_userId: string | null) {
    // No-op: authentication is handled via HTTP-only cookies
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
      credentials: 'include',  // Send cookies for authentication
    });

    if (!response.ok) {
      const error: ApiError = await response.json().catch(() => ({
        detail: `HTTP error ${response.status}`,
      }));
      throw new Error(error.detail);
    }

    // Handle empty responses
    const text = await response.text();
    if (!text) {
      return {} as T;
    }
    return JSON.parse(text);
  }

  // Auth endpoints
  async getAuthorizationUrl(): Promise<{ authorization_url: string; state: string }> {
    return this.request('/auth/authorize');
  }

  async getMe(): Promise<User> {
    return this.request('/users/me');
  }

  async getTokenStatus(): Promise<{ is_valid: boolean; expires_at: string | null; message: string }> {
    return this.request('/auth/token-status');
  }

  async logout(): Promise<void> {
    return this.request('/auth/logout', { method: 'POST' });
  }

  async refreshToken(): Promise<{ message: string; expires_at: string }> {
    return this.request('/auth/refresh', { method: 'POST' });
  }

  // Sync config endpoints
  async listSyncConfigs(): Promise<SyncConfig[]> {
    return this.request('/sync-configs');
  }

  async createSyncConfig(data: Partial<SyncConfig>): Promise<SyncConfig> {
    return this.request('/sync-configs', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getSyncConfig(id: number): Promise<SyncConfig> {
    return this.request(`/sync-configs/${id}`);
  }

  async updateSyncConfig(id: number, data: Partial<SyncConfig>): Promise<SyncConfig> {
    return this.request(`/sync-configs/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteSyncConfig(id: number): Promise<void> {
    return this.request(`/sync-configs/${id}`, { method: 'DELETE' });
  }

  async triggerSync(configId: number): Promise<{ sync_run_id: number; status: string; message: string; queue_position?: number | null }> {
    return this.request(`/sync-configs/${configId}/run`, { method: 'POST' });
  }

  async listWikiSpaces(): Promise<WikiSpace[]> {
    return this.request('/sync-configs/wiki-spaces');
  }

  // Sync run endpoints
  async listSyncRuns(params?: {
    config_id?: number;
    status_filter?: string;
    page?: number;
    page_size?: number;
  }): Promise<{ items: SyncRun[]; total: number; page: number; page_size: number }> {
    const searchParams = new URLSearchParams();
    if (params?.config_id) searchParams.set('config_id', params.config_id.toString());
    if (params?.status_filter) searchParams.set('status_filter', params.status_filter);
    if (params?.page) searchParams.set('page', params.page.toString());
    if (params?.page_size) searchParams.set('page_size', params.page_size.toString());

    const query = searchParams.toString();
    return this.request(`/sync-runs${query ? `?${query}` : ''}`);
  }

  async getSyncRun(id: number): Promise<SyncRun> {
    return this.request(`/sync-runs/${id}`);
  }

  async getSyncRunFiles(id: number, status?: FileStatus): Promise<SyncFileRecordList> {
    const params = status ? `?status_filter=${status}` : '';
    return this.request(`/sync-runs/${id}/files${params}`);
  }

  async cancelSyncRun(id: number): Promise<SyncRun> {
    return this.request(`/sync-runs/${id}/cancel`, { method: 'POST' });
  }

  // SSE stream URL
  getSyncRunStreamUrl(id: number): string {
    return `${this.baseUrl}/sync-runs/${id}/stream`;
  }
}

export const api = new ApiClient();
export default api;
