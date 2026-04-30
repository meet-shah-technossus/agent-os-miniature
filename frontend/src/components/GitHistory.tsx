/* Git & History — bus history for pipeline events, module lifecycle */

import { useEffect, useState } from 'react';
import { api } from '../hooks/api';
import type { BusMessage } from '../types';

const eventIcons: Record<string, string> = {
  git_commit: '📝',
  git_push: '⬆️',
  pr_created: '🔀',
  pr_merged: '✅',
  release_pr_created: '🚀',
  module_complete: '🎉',
  pipeline_complete: '🏁',
  decision: '🔍',
};

const eventColors: Record<string, string> = {
  git_commit: 'bg-blue-500',
  git_push: 'bg-cyan-500',
  pr_created: 'bg-purple-500',
  pr_merged: 'bg-green-500',
  release_pr_created: 'bg-amber-500',
  module_complete: 'bg-green-500',
  pipeline_complete: 'bg-emerald-500',
};

function EventDetail({ payload }: { payload: Record<string, unknown> }) {
  const event = payload.event as string;

  if (event === 'git_commit') {
    const branch = payload.branch as string | undefined;
    const sha = payload.commit_sha as string | undefined;
    const pushed = payload.pushed as boolean | undefined;
    const repoUrl = payload.repo_url as string | undefined;
    return (
      <div className="text-xs text-slate-400 mt-1 space-y-0.5">
        {branch && <div>Branch: <span className="text-indigo-400">{branch}</span></div>}
        {sha && <div>SHA: <span className="text-slate-300">{sha}</span></div>}
        {pushed && <div className="text-cyan-400">Pushed to remote</div>}
        {repoUrl && (
          <div>
            <a
              href={repoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-purple-400 hover:text-purple-300"
            >
              {repoUrl}
            </a>
          </div>
        )}
      </div>
    );
  }

  if (event === 'git_push') {
    const branch = payload.branch as string | undefined;
    const repoUrl = payload.repo_url as string | undefined;
    return (
      <div className="text-xs text-cyan-400 mt-1 space-y-0.5">
        <div>Pushed <span className="text-indigo-400">{branch || 'main'}</span> to GitHub</div>
        {repoUrl && (
          <a
            href={repoUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-purple-400 hover:text-purple-300"
          >
            {repoUrl}
          </a>
        )}
      </div>
    );
  }

  if (event === 'module_complete') {
    const moduleId = payload.module_id as string | undefined;
    const pushed = payload.pushed as boolean | undefined;
    const repoUrl = payload.repo_url as string | undefined;
    return (
      <div className="text-xs text-green-400 mt-1 space-y-0.5">
        <div>Module <span className="font-semibold">{moduleId}</span> completed</div>
        {pushed && repoUrl && (
          <div>
            Code live at{' '}
            <a
              href={repoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-purple-400 hover:text-purple-300"
            >
              {repoUrl}
            </a>
          </div>
        )}
      </div>
    );
  }

  // Fallback: raw JSON
  return (
    <pre className="text-xs text-slate-400 mt-1 overflow-x-auto">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}

export default function GitHistory() {
  const [events, setEvents] = useState<BusMessage[]>([]);

  useEffect(() => {
    const load = () => {
      api.getBusHistory('pipeline_events').then(setEvents).catch(() => {});
    };
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="glass-card">
      <h2 className="text-sm font-semibold mb-3">Pipeline Events Timeline</h2>
      {events.length === 0 ? (
        <p className="text-[var(--text-secondary)] text-sm">No events recorded yet.</p>
      ) : (
        <div className="relative pl-6">
          <div className="absolute left-2 top-0 bottom-0 w-px bg-indigo-500/30" />
          {events.map((ev, i) => {
            const eventType = (ev.payload.event as string) || '';
            const icon = eventIcons[eventType] || '•';
            const dotColor = eventColors[eventType] || 'bg-indigo-500';
            return (
              <div key={i} className="relative mb-4">
                <div className={`absolute -left-4 top-1 w-2 h-2 rounded-full ${dotColor}`} />
                <div className="text-xs text-[var(--text-secondary)]">
                  {new Date(ev.timestamp).toLocaleString()}
                </div>
                <div className="text-sm mt-0.5">
                  <span className="mr-1">{icon}</span>
                  <span className="text-slate-300">{ev.sender}</span>
                  {ev.module_id && (
                    <span className="text-indigo-400 ml-2">{ev.module_id}</span>
                  )}
                  {eventType && (
                    <span className="text-[var(--text-secondary)] ml-2 text-xs">
                      ({eventType.replace(/_/g, ' ')})
                    </span>
                  )}
                </div>
                <EventDetail payload={ev.payload} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
