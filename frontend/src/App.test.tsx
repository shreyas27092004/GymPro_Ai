// src/App.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import App from './App';

describe('App Component', () => {
  it('renders GymPro AI navigation brand and landing heading', () => {
    render(<App />);
    expect(screen.getByText(/GymPro/i)).toBeInTheDocument();
    expect(screen.getByText(/Strict Human Safety/i)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /Get Started/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /Sign in/i }).length).toBeGreaterThan(0);
  });
});
