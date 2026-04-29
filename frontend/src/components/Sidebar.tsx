/* Sidebar navigation with tab buttons */

import { motion } from 'framer-motion';

const tabs = [
  { id: 'pipeline', label: 'Pipeline', icon: '⚙' },
  { id: 'terminal', label: 'Terminal', icon: '▸' },
  { id: 'insights', label: 'Code Insights', icon: '◈' },
  { id: 'prompt-editor', label: 'Prompt Editor', icon: '✎' },
  { id: 'module-editor', label: 'Module Editor', icon: '❐' },
  { id: 'review-editor', label: 'Review Editor', icon: '✓' },
  { id: 'git', label: 'Git & History', icon: '⎇' },
  { id: 'metrics', label: 'Metrics', icon: '◔' },
  { id: 'settings', label: 'Settings', icon: '⚡' },
] as const;

export type TabId = (typeof tabs)[number]['id'];

interface Props {
  active: TabId;
  onSelect: (id: TabId) => void;
}

export default function Sidebar({ active, onSelect }: Props) {
  return (
    <nav className="w-56 shrink-0 flex flex-col gap-1 p-3 border-r border-[var(--border-glass)]">
      <h1 className="text-lg font-bold mb-4 px-2 bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
        Agent OS
      </h1>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onSelect(tab.id)}
          className={`relative text-left px-3 py-2 rounded-lg text-sm transition-colors ${
            active === tab.id
              ? 'text-white'
              : 'text-[var(--text-secondary)] hover:text-white hover:bg-white/5'
          }`}
        >
          {active === tab.id && (
            <motion.div
              layoutId="sidebar-active"
              className="absolute inset-0 rounded-lg bg-indigo-500/20 border border-indigo-500/30"
              transition={{ type: 'spring', stiffness: 350, damping: 30 }}
            />
          )}
          <span className="relative z-10">
            {tab.icon} {tab.label}
          </span>
        </button>
      ))}
    </nav>
  );
}
