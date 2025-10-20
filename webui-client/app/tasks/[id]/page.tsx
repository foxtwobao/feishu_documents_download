'use client';

import { useMemo } from 'react';
import TaskStreamView from '../../../components/TaskStreamView';
import UserGate from '../../../components/UserGate';

export default function TaskDetailPage({ params }: { params: { id: string } }): JSX.Element {
  const taskId = useMemo(() => params.id, [params.id]);
  return (
    <UserGate>
      <TaskStreamView taskId={taskId} />
    </UserGate>
  );
}
