/* WebSocket hook — connects to the Agent OS backend WS and streams messages.
   Auto-reconnects with exponential back-off on disconnect. */

import { useEffect, useRef, useState, useCallback } from 'react';
import type { BusMessage } from '../types';
import { WS_RECONNECT_BASE_MS, WS_RECONNECT_MAX_MS } from '../constants';

const _BASE_DELAY_MS = WS_RECONNECT_BASE_MS;
const _MAX_DELAY_MS  = WS_RECONNECT_MAX_MS;

export function useWebSocket() {
  const [messages, setMessages] = useState<BusMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef        = useRef<WebSocket | null>(null);
  const retryRef     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef   = useRef(0);
  const mountedRef   = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      setConnected(true);
      attemptRef.current = 0;
    };

    ws.onclose = () => {
      setConnected(false);
      if (!mountedRef.current) return;
      // Exponential back-off: 1 s, 2 s, 4 s … capped at 30 s
      const delay = Math.min(_BASE_DELAY_MS * 2 ** attemptRef.current, _MAX_DELAY_MS);
      attemptRef.current += 1;
      retryRef.current = setTimeout(connect, delay);
    };

    ws.onmessage = (ev) => {
      try {
        const msg: BusMessage = JSON.parse(ev.data);
        setMessages((prev) => [...prev.slice(-499), msg]);
      } catch {
        /* ignore non-JSON frames */
      }
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (retryRef.current) clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const subscribe = useCallback((channels: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ subscribe: channels }));
    }
  }, []);

  return { messages, connected, subscribe };
}
