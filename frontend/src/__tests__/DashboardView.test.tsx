import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import DashboardView from '../components/DashboardView'

// Mock hooks and API to prevent real network calls
vi.mock('../hooks/usePipelineFlow', () => ({
  usePipelineFlow: () => ({
    pipelineStatus: 'IDLE',
    isHitlGate: false,
    currentIteration: 0,
    statusText: 'Idle',
    loading: false,
  }),
}))

vi.mock('../hooks/api', () => ({
  api: {
    getStoryQueue: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    resetPipeline: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('../components/PipelineFlowDiagram', () => ({
  default: () => <div data-testid="pipeline-flow-diagram" />,
}))

describe('DashboardView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without crashing', () => {
    render(<DashboardView />)
  })

  it('renders the pipeline flow diagram', () => {
    render(<DashboardView />)
    expect(screen.getByTestId('pipeline-flow-diagram')).toBeDefined()
  })
})
