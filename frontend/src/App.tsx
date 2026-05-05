import { useState } from 'react';
import Sidebar, { type TabId } from './components/Sidebar';
import DashboardView from './components/DashboardView';
import PipelineView from './components/PipelineView';
import TerminalStreams from './components/TerminalStreams';
import CodeInsights from './components/CodeInsights';
import PromptEditor from './components/PromptEditor';
import ModuleEditor from './components/ModuleEditor';
import ReviewEditor from './components/ReviewEditor';
import GitHistory from './components/GitHistory';
import MetricsDashboard from './components/MetricsDashboard';
import SettingsView from './components/SettingsView';
import AgentsView from './components/AgentsView';
import AgentTerminalHub from './components/AgentTerminalHub';
import WorkflowView from './components/WorkflowView';
import ProjectsView from './components/ProjectsView';
import NotificationTray from './components/NotificationTray';
import { useWebSocket } from './hooks/useWebSocket';
import { useAgentTerminals } from './hooks/useAgentTerminals';
import { useNotifications } from './hooks/useNotifications';

export default function App() {
  const [tab, setTab] = useState<TabId>('dashboard');
  const { messages, connected } = useWebSocket();
  const { states: agentTerminalStates, connected: termConnected, activeAgentPosts } = useAgentTerminals();
  const { notifications, dismiss, clearAll } = useNotifications(messages);

  return (
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
        {tab === 'pipeline'      && <PipelineView />}
        {tab === 'workflow'      && <WorkflowView />}
        {tab === 'projects'      && <ProjectsView />}
        {tab === 'terminal'      && <TerminalStreams messages={messages} />}
        {tab === 'terminal-hub'  && (
          <AgentTerminalHub states={agentTerminalStates} wsConnected={termConnected} />
        )}
        {tab === 'insights'      && <CodeInsights />}
        {tab === 'prompt-editor' && <PromptEditor />}
        {tab === 'module-editor' && <ModuleEditor />}
        {tab === 'review-editor' && <ReviewEditor />}
        {tab === 'git'           && <GitHistory />}
        {tab === 'metrics'       && <MetricsDashboard />}
        {tab === 'agents'        && <AgentsView />}
        {tab === 'settings'      && <SettingsView />}
      </main>
    </div>
  );
}

