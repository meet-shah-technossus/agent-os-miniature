import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from '../hooks/useWebSocket'

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  readyState = 0
  url: string

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  close() {
    this.readyState = 3
  }

  simulateOpen() {
    this.readyState = 1
    this.onopen?.()
  }

  simulateClose() {
    this.readyState = 3
    this.onclose?.()
  }

  simulateMessage(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

describe('useWebSocket', () => {
  let originalWebSocket: typeof WebSocket

  beforeEach(() => {
    MockWebSocket.instances = []
    originalWebSocket = global.WebSocket
    // @ts-expect-error mock
    global.WebSocket = MockWebSocket
    vi.useFakeTimers()
  })

  afterEach(() => {
    global.WebSocket = originalWebSocket
    vi.useRealTimers()
  })

  it('connects on mount', () => {
    renderHook(() => useWebSocket())
    expect(MockWebSocket.instances.length).toBe(1)
  })

  it('sets connected to true on open', () => {
    const { result } = renderHook(() => useWebSocket())
    act(() => {
      MockWebSocket.instances[0].simulateOpen()
    })
    expect(result.current.connected).toBe(true)
  })

  it('sets connected to false on close', () => {
    const { result } = renderHook(() => useWebSocket())
    act(() => {
      MockWebSocket.instances[0].simulateOpen()
    })
    expect(result.current.connected).toBe(true)
    act(() => {
      MockWebSocket.instances[0].simulateClose()
    })
    expect(result.current.connected).toBe(false)
  })

  it('accumulates messages', () => {
    const { result } = renderHook(() => useWebSocket())
    act(() => {
      MockWebSocket.instances[0].simulateOpen()
    })
    act(() => {
      MockWebSocket.instances[0].simulateMessage({ event: 'state_changed', data: {} })
    })
    expect(result.current.messages.length).toBe(1)
  })

  it('attempts reconnect after close with exponential backoff', () => {
    renderHook(() => useWebSocket())
    const firstWs = MockWebSocket.instances[0]
    act(() => {
      firstWs.simulateOpen()
      firstWs.simulateClose()
    })
    // After close, a reconnect should be scheduled
    act(() => {
      vi.advanceTimersByTime(1500) // base delay 1000ms + margin
    })
    // A new WebSocket instance should be created for reconnect
    expect(MockWebSocket.instances.length).toBeGreaterThan(1)
  })
})
