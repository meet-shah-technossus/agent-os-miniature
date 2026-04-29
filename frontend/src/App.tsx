import { useState } from 'react';
import Sidebar, { type TabId } from './components/Sidebar';
import PipelineView from './components/PipelineView';
import TerminalStreams from './components/TerminalStreams';
import CodeInsights from './components/CodeInsights';
import PromptEditor from './components/PromptEditor';
import ModuleEditor from './components/ModuleEditor';
import ReviewEditor from './components/ReviewEditor';
import GitHistory from './components/GitHistory';
import MetricsDashboard from './components/MetricsDashboard';
import SettingsView from './components/SettingsView';
import { useWebSocket } from './hooks/useWebSocket';

export default function App() {
  const [tab, setTab] = useState<TabId>('pipeline');
  const { messages, connected } = useWebSocket();

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar active={tab} onSelect={setTab} />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="flex items-center justify-end mb-4 gap-2">
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-xs text-[var(--text-secondary)]">
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        {tab === 'pipeline' && <PipelineView />}
        {tab === 'terminal' && <TerminalStreams messages={messages} />}
        {tab === 'insights' && <CodeInsights />}
        {tab === 'prompt-editor' && <PromptEditor />}
        {tab === 'module-editor' && <ModuleEditor />}
        {tab === 'review-editor' && <ReviewEditor />}
        {tab === 'git' && <GitHistory />}
        {tab === 'metrics' && <MetricsDashboard />}
        {tab === 'settings' && <SettingsView />}
      </main>
    </div>
  );
}
