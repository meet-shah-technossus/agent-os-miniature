import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock the api module
const mockGetPipelineStatus = vi.fn()
vi.mock('../hooks/api', () => ({
  api: {
    getPipelineStatus: () => mockGetPipelineStatus(),
  },
}))

import { PipelineProvider, usePipelineStatus } from '../contexts/PipelineContext'

function Consumer() {
  const { status, loading, error } = usePipelineStatus()
  if (loading) return <div data-testid="loading">Loading</div>
  if (error) return <div data-testid="error">{error}</div>
  return <div data-testid="status">{status?.pipeline_status ?? 'none'}</div>
}

describe('PipelineContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows loading initially', () => {
    mockGetPipelineStatus.mockReturnValue(new Promise(() => {})) // never resolves
    render(
      <PipelineProvider>
        <Consumer />
      </PipelineProvider>
    )
    expect(screen.getByTestId('loading')).toBeDefined()
  })

  it('displays status after fetch resolves', async () => {
    mockGetPipelineStatus.mockResolvedValue({
      pipeline_status: 'IDLE',
      current_iteration: 0,
      is_hitl_gate: false,
    })
    render(
      <PipelineProvider>
        <Consumer />
      </PipelineProvider>
    )
    // Flush the fetch promise
    await vi.waitFor(() => {
      expect(screen.getByTestId('status')).toBeDefined()
    })
    expect(screen.getByTestId('status').textContent).toBe('IDLE')
  })

  it('displays error when fetch fails', async () => {
    mockGetPipelineStatus.mockRejectedValue(new Error('Network error'))
    render(
      <PipelineProvider>
        <Consumer />
      </PipelineProvider>
    )
    await vi.waitFor(() => {
      expect(screen.getByTestId('error')).toBeDefined()
    })
    expect(screen.getByTestId('error').textContent).toBe('Network error')
  })
})
