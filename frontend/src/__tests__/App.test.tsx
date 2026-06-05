import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

// Mock WebSocket hooks that require real network connections
vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: () => ({ messages: [], connected: false }),
}))
vi.mock('../hooks/useAgentTerminals', () => ({
  useAgentTerminals: () => ({ states: {}, connected: false, activeAgentPosts: [] }),
}))
vi.mock('../hooks/useNotifications', () => ({
  useNotifications: () => ({ notifications: [], dismiss: vi.fn(), clearAll: vi.fn() }),
}))

import App from '../App'

describe('App', () => {
  it('renders without crashing', () => {
    const { container } = render(<App />)
    expect(container).toBeTruthy()
  })
})
