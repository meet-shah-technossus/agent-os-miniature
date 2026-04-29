/* WebSocket hook — connects to the Agent OS backend WS and streams messages. */

import { useEffect, useRef, useState, useCallback } from 'react';
import type { BusMessage } from '../types';

export function useWebSocket() {
  const [messages, setMessages] = useState<BusMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (ev) => {
      try {
        const msg: BusMessage = JSON.parse(ev.data);
        setMessages((prev) => [...prev.slice(-499), msg]);
      } catch {
        /* ignore non-JSON */
      }
    };

    return () => {
      ws.close();
    };
  }, []);

  const subscribe = useCallback((channels: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ subscribe: channels }));
    }
  }, []);

  return { messages, connected, subscribe };
}
