// src/__tests__/consoles.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemberDashboard } from '../pages/member/MemberDashboard';
import { TrainerConsole } from '../pages/trainer/TrainerConsole';
import { AdminConsole } from '../pages/admin/AdminConsole';
import { PrivacyPage } from '../pages/member/PrivacyPage';
import { AuthProvider } from '../auth/AuthContext';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
});

describe('Consoles & Privacy Components', () => {
  it('renders MemberDashboard with activity stats and class schedule', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemberDashboard onOpenCoach={vi.fn()} />
        </AuthProvider>
      </QueryClientProvider>
    );

    expect(screen.getByText(/Welcome back/i)).toBeInTheDocument();
    expect(screen.getByText(/Current Entitlement/i)).toBeInTheDocument();
    expect(screen.getByText(/Today's Targets/i)).toBeInTheDocument();
    expect(screen.getByText(/Class Schedule & Booking/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Report an Issue/i })).toBeInTheDocument();
  });

  it('renders TrainerConsole with roster and series generator', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <TrainerConsole onOpenCoach={vi.fn()} />
        </AuthProvider>
      </QueryClientProvider>
    );

    expect(screen.getByText(/Trainer Operations Console/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Class Rosters & Attendance/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Recurring Series Creator/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Availability & Time Off/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Member Reviews & Feedback/i })).toBeInTheDocument();
  });

  it('allows clicking attendee Present and Absent buttons in TrainerConsole', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <TrainerConsole onOpenCoach={vi.fn()} />
        </AuthProvider>
      </QueryClientProvider>
    );

    // Wait for attendee name to render
    const johnAttendee = await screen.findByText('John');
    expect(johnAttendee).toBeInTheDocument();

    // Find the Present button and click it
    const presentButtons = screen.getAllByRole('button', { name: /Mark Present|Present/i });
    expect(presentButtons.length).toBeGreaterThan(0);
    fireEvent.click(presentButtons[0]);

    // John should now be marked Present
    await waitFor(() => {
      expect(screen.getByText(/Marked for John as Present/i)).toBeInTheDocument();
    });

    // Find the Absent button for Priya and click it
    const absentButtons = screen.getAllByRole('button', { name: /Mark Absent|Absent/i });
    expect(absentButtons.length).toBeGreaterThan(0);
    fireEvent.click(absentButtons[1]);

    await waitFor(() => {
      expect(screen.getByText(/Marked for Priya as Absent/i)).toBeInTheDocument();
    });
  });

  it('renders AdminConsole with KPI catalog and security guarantees', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <AdminConsole onOpenCoach={vi.fn()} />
        </AuthProvider>
      </QueryClientProvider>
    );

    expect(screen.getByText(/Gym Governance & Administration/i)).toBeInTheDocument();
    expect(screen.getByText(/Monthly Recurring Revenue/i)).toBeInTheDocument();
    expect(screen.getByText(/Class Occupancy Rate/i)).toBeInTheDocument();
    expect(screen.getByText(/Metric Catalog Invariants/i)).toBeInTheDocument();
  });

  it('renders PrivacyPage with affirmative consent controls and export button', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <PrivacyPage />
        </AuthProvider>
      </QueryClientProvider>
    );

    expect(screen.getByText(/Data Privacy & AI Memory Controls/i)).toBeInTheDocument();
    expect(screen.getByText(/Health & Biometric Data Consent/i)).toBeInTheDocument();
    expect(screen.getByText(/What the AI Remembers/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Export My Data/i })).toBeInTheDocument();
  });
});
