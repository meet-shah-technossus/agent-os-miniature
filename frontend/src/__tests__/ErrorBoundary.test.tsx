import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import type { ReactNode } from 'react'
import ErrorBoundary from '../components/ErrorBoundary'

function ThrowingComponent(): ReactNode {
  throw new Error('Test error')
}

function GoodComponent() {
  return <div data-testid="good">All good</div>
}

describe('ErrorBoundary', () => {
  // Suppress console.error during expected error boundary test
  const originalConsoleError = console.error
  beforeAll(() => {
    console.error = vi.fn()
  })
  afterAll(() => {
    console.error = originalConsoleError
  })

  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <GoodComponent />
      </ErrorBoundary>
    )
    expect(screen.getByTestId('good')).toBeDefined()
  })

  it('renders fallback UI when child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    )
    expect(screen.getByText('Something went wrong')).toBeDefined()
  })

  it('displays the error message', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    )
    expect(screen.getByText('Test error')).toBeDefined()
  })

  it('renders custom fallback when provided', () => {
    render(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">Custom</div>}>
        <ThrowingComponent />
      </ErrorBoundary>
    )
    expect(screen.getByTestId('custom-fallback')).toBeDefined()
  })

  it('shows Try Again button', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    )
    expect(screen.getByText('Try Again')).toBeDefined()
  })
})
