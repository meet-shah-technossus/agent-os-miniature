/* Metrics Dashboard — token usage, module progress, pipeline summary */

import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { api } from '../hooks/api';
import type { Metrics, Module } from '../types';

const PIE_COLORS = ['#22c55e', '#eab308', '#ef4444', '#64748b'];

export default function MetricsDashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [modules, setModules] = useState<Module[]>([]);

  useEffect(() => {
    api.getMetrics().then(setMetrics).catch(() => {});
    api.getModules().then(setModules).catch(() => {});
  }, []);

  const pieData = metrics
    ? [
        { name: 'Completed', value: metrics.completed_modules },
        { name: 'In Progress', value: metrics.total_modules - metrics.completed_modules - metrics.failed_modules },
        { name: 'Failed', value: metrics.failed_modules },
      ].filter((d) => d.value > 0)
    : [];

  const barData = modules.map((m) => ({
    name: m.name.length > 12 ? m.name.slice(0, 12) + '…' : m.name,
    order: m.execution_order,
    version: m.version,
  }));

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Modules', value: metrics.total_modules },
            { label: 'Completed', value: metrics.completed_modules },
            { label: 'Iterations', value: metrics.total_iterations },
            { label: 'Tokens Used', value: metrics.total_token_usage.toLocaleString() },
          ].map((card) => (
            <div key={card.label} className="glass-card text-center">
              <p className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">
                {card.label}
              </p>
              <p className="text-2xl font-bold mt-1">{card.value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Module progress chart */}
        {barData.length > 0 && (
          <div className="glass-card">
            <h3 className="text-sm font-semibold mb-3">Modules by Execution Order</h3>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={barData}>
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#1e293b', border: 'none', borderRadius: 8, color: '#f1f5f9' }} />
                <Bar dataKey="order" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Status pie chart */}
        {pieData.length > 0 && (
          <div className="glass-card">
            <h3 className="text-sm font-semibold mb-3">Module Status Distribution</h3>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  dataKey="value"
                  label={({ name, value }) => `${name}: ${value}`}
                >
                  {pieData.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ background: '#1e293b', border: 'none', borderRadius: 8, color: '#f1f5f9' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
