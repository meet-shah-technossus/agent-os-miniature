import { lazy, Suspense, useState } from 'react';
import Sidebar, { type TabId } from './components/Sidebar';
import DashboardView from './components/DashboardView';
import CommandCenter from './components/CommandCenter';
import NotificationTray from './components/NotificationTray';
import ErrorBoundary from './components/ErrorBoundary';
import { useWebSocket } from './hooks/useWebSocket';
import { useAgentTerminals } from './hooks/useAgentTerminals';
import { useNotifications } from './hooks/useNotifications';

// Phase 14.4: Lazy-load heavy secondary views
const CodeInsights = lazy(() => import('./components/CodeInsights'));
const GitHistory = lazy(() => import('./components/GitHistory'));
const MetricsDashboard = lazy(() => import('./components/MetricsDashboard'));
const SettingsView = lazy(() => import('./components/SettingsView'));
const AgentsView = lazy(() => import('./components/AgentsView'));
const WorkflowView = lazy(() => import('./components/WorkflowView'));
const ProjectsView = lazy(() => import('./components/ProjectsView'));

export default function App() {
  const [tab, setTab] = useState<TabId>('dashboard');
  const { messages, connected } = useWebSocket();
  const { states: agentTerminalStates, connected: termConnected, activeAgentPosts } = useAgentTerminals();
  const { notifications, dismiss, clearAll } = useNotifications(messages);

  return (
    <ErrorBoundary>
    <div className="flex h-screen overflow-hidden">
      <Sidebar active={tab} onSelect={setTab} activeAgentPosts={activeAgentPosts} />
      <main className="flex-1 overflow-y-auto p-6">
        {/* Top bar: connection status + notification tray */}
        <div className="flex items-center justify-end mb-4 gap-3">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-xs text-[var(--text-secondary)]">
            {connected ? 'Connected' : 'Disconnected'}
          </span>
          <NotificationTray
            notifications={notifications}
            onDismiss={dismiss}
            onClearAll={clearAll}
          />
        </div>

        {tab === 'dashboard'     && <DashboardView />}
        <Suspense fallback={<div className="flex items-center justify-center h-64 text-white/40 text-sm">Loading…</div>}>
          {tab === 'workflow'      && <WorkflowView />}
          {tab === 'projects'      && <ProjectsView />}
          {tab === 'insights'      && <CodeInsights />}
          {tab === 'git'           && <GitHistory />}
          {tab === 'metrics'       && <MetricsDashboard />}
          {tab === 'agents'        && <AgentsView />}
          {tab === 'settings'      && <SettingsView />}
        </Suspense>
        <div style={{ display: tab === 'terminal-hub' ? undefined : 'none' }}>
          <CommandCenter terminalStates={agentTerminalStates} wsConnected={termConnected} messages={messages} />
        </div>
      </main>
    </div>
    </ErrorBoundary>
  );
}

