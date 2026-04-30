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
  next_module: '▶️',
  pipeline_complete: '🏁',
  decision: '🔍',
  repo_created: '🏗️',
};

const eventColors: Record<string, string> = {
  git_commit: 'bg-blue-500',
  git_push: 'bg-cyan-500',
  pr_created: 'bg-purple-500',
  pr_merged: 'bg-green-500',
  release_pr_created: 'bg-amber-500',
  module_complete: 'bg-green-500',
  next_module: 'bg-indigo-500',
  pipeline_complete: 'bg-emerald-500',
  repo_created: 'bg-violet-500',
};

/** GitHub-action events emitted by the code_reviewer agent. */
const GITHUB_EVENTS = new Set(['git_commit', 'git_push', 'repo_created']);

function RepoLink({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-purple-400 hover:text-purple-300 break-all"
    >
      <span>🔗</span>
      {url.replace('https://github.com/', '')}
    </a>
  );
}

function EventDetail({ payload }: { payload: Record<string, unknown> }) {
  const event = payload.event as string;

  if (event === 'git_commit') {
    const branch = payload.branch as string | undefined;
    const sha = payload.commit_sha as string | undefined;
    const pushed = payload.pushed as boolean | undefined;
    const repoUrl = payload.repo_url as string | undefined;
    return (
      <div className="text-xs text-slate-400 mt-1 space-y-0.5">
        {branch && <div>Branch: <span className="text-indigo-400 font-mono">{branch}</span></div>}
        {sha && <div>SHA: <span className="text-slate-300 font-mono">{sha.slice(0, 12)}</span></div>}
        {pushed
          ? <div className="text-cyan-400 font-medium">✓ Pushed to GitHub</div>
          : <div className="text-slate-500">Local commit only (push disabled or failed)</div>
        }
        {repoUrl && <RepoLink url={repoUrl} />}
      </div>
    );
  }

  if (event === 'git_push') {
    const branch = payload.branch as string | undefined;
    const repoUrl = payload.repo_url as string | undefined;
    return (
      <div className="text-xs mt-1 space-y-0.5">
        <div className="text-cyan-400 font-medium">
          ✓ Pushed <span className="font-mono text-indigo-300">{branch || 'main'}</span> → GitHub
        </div>
        {repoUrl && <RepoLink url={repoUrl} />}
      </div>
    );
  }

  if (event === 'repo_created') {
    const repoUrl = payload.repo_url as string | undefined;
    const repoName = payload.repo_name as string | undefined;
    return (
      <div className="text-xs mt-1 space-y-0.5">
        <div className="text-violet-400 font-medium">✓ GitHub repository created</div>
        {repoName && <div className="text-slate-300 font-mono">{repoName}</div>}
        {repoUrl && <RepoLink url={repoUrl} />}
      </div>
    );
  }

  if (event === 'module_complete') {
    const moduleId = payload.module_id as string | undefined;
    const pushed = payload.pushed as boolean | undefined;
    const repoUrl = payload.repo_url as string | undefined;
    return (
      <div className="text-xs text-green-400 mt-1 space-y-0.5">
        <div>Module <span className="font-semibold font-mono">{moduleId}</span> completed</div>
        {pushed && repoUrl && (
          <div className="text-slate-400">
            Code live at <RepoLink url={repoUrl} />
          </div>
        )}
      </div>
    );
  }

  if (event === 'next_module') {
    const moduleId = payload.module_id as string | undefined;
    const moduleName = payload.module_name as string | undefined;
    const completed = payload.completed as number | undefined;
    const remaining = payload.remaining as number | undefined;
    return (
      <div className="text-xs text-indigo-300 mt-1 space-y-0.5">
        <div>Starting <span className="font-semibold font-mono">{moduleId}</span>{moduleName ? ` — ${moduleName}` : ''}</div>
        {completed !== undefined && remaining !== undefined && (
          <div className="text-slate-400">{completed} done · {remaining} remaining</div>
        )}
      </div>
    );
  }

  if (event === 'decision') {
    const decision = payload.decision as string | undefined;
    const score = payload.convergence_score as number | undefined;
    const colorMap: Record<string, string> = {
      MODULE_COMPLETE: 'text-green-400',
      ITERATE: 'text-yellow-400',
      HITL_4_MAX_ITERATIONS: 'text-red-400',
    };
    return (
      <div className={`text-xs mt-1 space-y-0.5 ${colorMap[decision || ''] || 'text-slate-400'}`}>
        <div>Decision: <span className="font-semibold">{decision}</span></div>
        {score !== undefined && <div className="text-slate-400">Score: {score}</div>}
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

/** Compact card showing the latest GitHub push/commit for the code-reviewer agent. */
function GitHubActivityBanner({ events }: { events: BusMessage[] }) {
  const ghEvents = events
    .filter(ev => GITHUB_EVENTS.has(ev.payload.event as string))
    .slice(-5)  // last 5 GitHub events
    .reverse(); // newest first

  if (ghEvents.length === 0) return null;

  const latestPush = events
    .filter(ev => ev.payload.event === 'git_push')
    .at(-1);
  const repoUrl = latestPush?.payload.repo_url as string | undefined;

  return (
    <div className="glass-card border border-cyan-500/20 mb-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-cyan-400">⬆️ GitHub Actions (Code Reviewer)</h3>
        {repoUrl && (
          <a
            href={repoUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1"
          >
            View Repo →
          </a>
        )}
      </div>
      <div className="space-y-1">
        {ghEvents.map((ev, i) => {
          const event = ev.payload.event as string;
          const icon = eventIcons[event] || '•';
          const branch = ev.payload.branch as string | undefined;
          const sha = ev.payload.commit_sha as string | undefined;
          const moduleId = ev.module_id;
          return (
            <div key={i} className="flex items-start gap-2 text-xs py-1 border-t border-slate-700/40 first:border-0">
              <span className="text-base leading-none mt-0.5">{icon}</span>
              <div className="flex-1 min-w-0">
                <span className="text-slate-300 font-medium">{event.replace(/_/g, ' ')}</span>
                {moduleId && <span className="text-indigo-400 ml-2 font-mono">{moduleId}</span>}
                {branch && <span className="text-slate-500 ml-2 font-mono">{branch}</span>}
                {sha && <span className="text-slate-600 ml-2 font-mono">{sha.slice(0, 8)}</span>}
                <span className="text-slate-600 ml-2">
                  {new Date(ev.timestamp).toLocaleTimeString()}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
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
    <div>
      {/* GitHub Actions banner — only shown when there are GitHub events */}
      <GitHubActivityBanner events={events} />

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
              const isGitHubEvent = GITHUB_EVENTS.has(eventType);
              return (
                <div key={i} className={`relative mb-4 ${isGitHubEvent ? 'pl-1 border-l-2 border-cyan-500/40' : ''}`}>
                  <div className={`absolute -left-4 top-1 w-2 h-2 rounded-full ${dotColor}`} />
                  <div className="text-xs text-[var(--text-secondary)]">
                    {new Date(ev.timestamp).toLocaleString()}
                    {isGitHubEvent && (
                      <span className="ml-2 text-cyan-500/70 font-medium">GitHub</span>
                    )}
                  </div>
                  <div className="text-sm mt-0.5">
                    <span className="mr-1">{icon}</span>
                    <span className={isGitHubEvent ? 'text-cyan-300' : 'text-slate-300'}>{ev.sender}</span>
                    {ev.module_id && (
                      <span className="text-indigo-400 ml-2 font-mono">{ev.module_id}</span>
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
    </div>
  );
}
