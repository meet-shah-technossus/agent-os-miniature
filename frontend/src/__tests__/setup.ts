import '@testing-library/jest-dom'

// Polyfill browser APIs not available in jsdom
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
