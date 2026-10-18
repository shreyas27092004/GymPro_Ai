import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from './App'

describe('App Component', () => {
  it('renders GymPro AI heading', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/GymPro/i)
    expect(screen.getByText(/Scaffold Ready/i)).toBeInTheDocument()
  })
})
