export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

export function apiUrl(path: string): string {
  if (!path.startsWith('/')) {
    return `${API_BASE_URL}/${path}`;
  }
  return `${API_BASE_URL}${path}`;
}

export type TaskParameter = {
  label: string;
  value: string;
};

export type TaskPlanSample = {
  name?: string | null;
  file_type?: string | null;
  action: string;
  detail?: string | null;
};

export type TaskPlanSummary = {
  total_files: number;
  will_download: number;
  existing: number;
  skipped: number;
  root?: {
    token?: string | null;
    name?: string | null;
  } | null;
  samples: TaskPlanSample[];
};

export type TaskArtifactPayload = {
  path: string;
  file_type?: string | null;
  created_at: string;
};

export type TaskStatusPayload = {
  id: number;
  task_type: string;
  status: string;
  progress: number;
  incremental: boolean;
  limit: number | null;
  created_at: string;
  scheduled_for: string | null;
  started_at: string | null;
  completed_at: string | null;
  result_path: string | null;
  error_message: string | null;
  description?: string | null;
  parameters?: TaskParameter[];
  current_item?: string | null;
  current_stage?: string | null;
  current_detail?: string | null;
  processed?: number | null;
  expected?: number | null;
  plan?: TaskPlanSummary | null;
  artifact_count?: number;
  download_ready?: boolean;
};

export type TaskLogPayload = {
  id: number;
  task_id: number;
  level: string;
  message: string;
  created_at: string;
};

export type TaskListResponse = {
  tasks: TaskStatusPayload[];
};

export type TaskDetailPayload = TaskStatusPayload & {
  logs: TaskLogPayload[];
  artifacts: TaskArtifactPayload[];
};

export type TaskPreviewResponse = {
  plan: TaskPlanSummary;
};

export function taskDownloadUrl(taskId: number): string {
  return apiUrl(`/tasks/${taskId}/download`);
}

export type TaskPreviewRequestBody = {
  task_type: string;
  payload: Record<string, unknown>;
  incremental: boolean;
  limit: number | null;
};

export async function fetchTaskPreview(userId: string, body: TaskPreviewRequestBody): Promise<TaskPreviewResponse> {
  const response = await fetch(apiUrl('/tasks/preview'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-ID': userId,
    },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    const error = new Error('auth_required');
    (error as Error & { authRequired?: boolean }).authRequired = true;
    throw error;
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `任务预览失败（${response.status}）`);
  }
  return (await response.json()) as TaskPreviewResponse;
}
