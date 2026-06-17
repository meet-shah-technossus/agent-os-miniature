import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { PipelineProvider } from './contexts/PipelineContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PipelineProvider>
      <App />
    </PipelineProvider>
  </StrictMode>,
)
