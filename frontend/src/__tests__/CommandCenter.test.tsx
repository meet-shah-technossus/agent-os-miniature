import { render } from '@testing-library/react'
import { describe, it, vi, beforeEach } from 'vitest'
import CommandCenter from '../components/CommandCenter'

// Mock @monaco-editor/react — it tries to load workers in jsdom which crashes
vi.mock('@monaco-editor/react', () => ({
  default: ({ value }: { value?: string }) => (
    <textarea data-testid="monaco-editor" defaultValue={value} />
  ),
}))

// Mock API
vi.mock('../hooks/api', () => ({
  api: {
    getPipelineStatus: vi.fn().mockResolvedValue({
      pipeline_status: 'IDLE',
      current_iteration: 0,
      last_checkpoint: '',
      metadata: {},
      is_hitl_gate: false,
      mode: 'standard',
      current_story_id: null,
      stories_completed: 0,
      stories_total: 0,
    }),
    getCurrentPrompt: vi.fn().mockResolvedValue(null),
    getCurrentReview: vi.fn().mockResolvedValue(null),
    getCliTools: vi.fn().mockResolvedValue({ tools: [] }),
    approvePrompt: vi.fn().mockResolvedValue({}),
    approveReview: vi.fn().mockResolvedValue({}),
    retryPromptGenerator: vi.fn().mockResolvedValue({}),
    startPipeline: vi.fn().mockResolvedValue({}),
    stopCodeGeneration: vi.fn().mockResolvedValue({}),
  },
}))

// Mock useAgentTerminals hook
vi.mock('../hooks/useAgentTerminals', () => ({
  POST_DISPLAY_NAME: {
    PROMPT_GENERATOR: 'Prompt Generator',
    CODE_GENERATOR: 'Code Generator',
    CODE_REVIEWER: 'Code Reviewer',
  },
  useAgentTerminals: () => ({}),
}))

// Mock TerminalPanel
vi.mock('../components/TerminalPanel', () => ({
  default: () => <div data-testid="terminal-panel" />,
}))

const defaultProps = {
  terminalStates: {},
  wsConnected: false,
  messages: [],
}

describe('CommandCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without crashing', () => {
    render(<CommandCenter {...defaultProps} />)
  })

  it('renders with ws connected', () => {
    render(<CommandCenter {...defaultProps} wsConnected={true} />)
  })

  it('renders with messages', () => {
    render(
      <CommandCenter
        {...defaultProps}
        messages={[
          {
            channel: 'pipeline',
            sender: 'orchestrator',
            event: 'run_started',
            timestamp: new Date().toISOString(),
            pipeline_status: 'IDLE',
            current_iteration: 0,
          } as any,
        ]}
      />,
    )
  })
})
