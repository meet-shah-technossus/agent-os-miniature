/* Terminal Streams — shows live bus messages in a scrollable log */

import { useRef, useEffect } from 'react';
import type { BusMessage } from '../types';

const channelColors: Record<string, string> = {
  module_updates: 'text-blue-400',
  prompt_ready: 'text-purple-400',
  generation_status: 'text-yellow-400',
  validation_results: 'text-cyan-400',
  review_feedback: 'text-orange-400',
  hitl_requests: 'text-red-400',
  hitl_responses: 'text-green-400',
  pipeline_events: 'text-indigo-400',
  error_alerts: 'text-red-500',
  agent_heartbeats: 'text-slate-400',
};

interface Props {
  messages: BusMessage[];
}

export default function TerminalStreams({ messages }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  return (
    <div className="glass-card h-[calc(100vh-8rem)] overflow-y-auto font-mono text-xs leading-relaxed">
      <h2 className="text-sm font-semibold mb-3 sticky top-0 bg-[var(--bg-primary)] pb-2">
        Live Bus Stream ({messages.length} messages)
      </h2>
      {messages.length === 0 && (
        <p className="text-[var(--text-secondary)]">Waiting for messages...</p>
      )}
      {messages.map((msg, i) => (
        <div key={i} className="border-b border-white/5 py-1.5">
          <span className="text-[var(--text-secondary)]">
            {new Date(msg.timestamp).toLocaleTimeString()}
          </span>{' '}
          <span className={channelColors[msg.channel] || 'text-white'}>
            [{msg.channel}]
          </span>{' '}
          <span className="text-slate-300">{msg.sender}</span>
          {msg.module_id && (
            <span className="text-[var(--text-secondary)]"> ({msg.module_id})</span>
          )}
          <div className="text-slate-400 pl-4 truncate">
            {JSON.stringify(msg.payload)}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
