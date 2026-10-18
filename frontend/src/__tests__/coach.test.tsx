// src/__tests__/coach.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GymProCoach } from '../coach/GymProCoach';
import { AuthProvider } from '../auth/AuthContext';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
});

const renderCoach = (isOpen = true) => {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <GymProCoach isOpen={isOpen} onClose={vi.fn()} conversationId="test-conv" />
      </AuthProvider>
    </QueryClientProvider>
  );
};

describe('GymProCoach Component', () => {
  it('does not render when isOpen is false', () => {
    const { container } = renderCoach(false);
    expect(container.firstChild).toBeNull();
  });

  it('renders header, safety badge, and voice invariant notice', () => {
    renderCoach(true);

    expect(screen.getByText('AI Fitness Concierge')).toBeInTheDocument();
    expect(
      screen.getByText(/I never change anything until you tap Confirm\. Voice never confirms\./i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Turn on spoken replies/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Start voice input/i })).toBeInTheDocument();
  });

  it('renders role-appropriate input placeholder and initial guidance', () => {
    renderCoach(true);

    const input = screen.getByPlaceholderText(/Try: Book tomorrow evening yoga/i);
    expect(input).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Send/i })).toBeInTheDocument();
  });

  it('renders default quick actions', () => {
    renderCoach(true);

    expect(screen.getByText('Book tomorrow evening yoga')).toBeInTheDocument();
    expect(screen.getByText('Which class is safe for my knee?')).toBeInTheDocument();
  });

  it('allows typing into the message input', () => {
    renderCoach(true);

    const input = screen.getByPlaceholderText(/Try: Book tomorrow evening yoga/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Schedule HIIT tomorrow' } });
    expect(input.value).toBe('Schedule HIIT tomorrow');
  });
});
