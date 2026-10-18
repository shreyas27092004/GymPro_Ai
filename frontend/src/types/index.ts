// src/types/index.ts

export type UserRole = 'USER' | 'TRAINER' | 'ADMIN';

export type AccountStatus =
  | 'ACTIVE'
  | 'EMAIL_UNVERIFIED'
  | 'PENDING_APPROVAL'
  | 'PENDING_ADMIN_CODE'
  | 'REJECTED'
  | 'EXPIRED'
  | 'SUSPENDED';

export interface UserSession {
  user_id: string;
  role: UserRole;
  account_status: string;
  plan?: string | null;
  full_name: string;
  email_masked: string;
  locale: string;
  timezone: string;
  age_years?: number | null;
  health_consent: boolean;
  is_minor: boolean;
  cooling_off_active: boolean;
}

export type QuickAction =
  | { type: 'CONFIRM'; action_id: string; label: string }
  | { type: 'CONFIRM_BUNDLE'; bundle_id: string; label: string }
  | { type: 'PROMPT'; label: string };

export interface BundleStep {
  step_no: number;
  type: string;
  summary: string;
  depends_on: number[];
  conditional_note?: string;
  result?: string;
}

export interface Bundle {
  bundle_id: string;
  headline: string;
  expires_at: string;
  steps: BundleStep[];
  questions: Array<{ agent: string; text: string }>;
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  actions?: QuickAction[];
  bundle?: Bundle | null;
}

export interface ClassSession {
  id: string;
  title: string;
  trainer_name?: string;
  category: string;
  impact: string;
  min_level: string;
  capacity: number;
  booked_count: number;
  start_time: string;
  end_time: string;
  status: string;
  injury_warning?: string | null;
}

export interface SeriesInstancePreview {
  start_time: string;
  end_time: string;
  status: 'OK' | 'CONFLICT_TRAINER_OVERLAP' | 'OUTSIDE_AVAILABILITY' | 'TIME_OFF' | 'PAST';
  conflict_details?: string | null;
}

export interface IssueReport {
  issue_id: string;
  reporter: string;
  category: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status: 'NEW' | 'IN_REVIEW' | 'ACTIONED' | 'CLOSED';
  summary: string;
  user_words?: string;
  admin_action?: string | null;
  created_at: string;
  handled_at?: string | null;
}

export interface TrainerRequest {
  request_id: string;
  user_id: string;
  full_name: string;
  email: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'MORE_INFO';
  specializations: string[];
  certifications: string[];
  bio?: string;
  risk_hints?: string[];
  created_at: string;
}

export interface AdminRequest {
  request_id: string;
  user_id: string;
  full_name: string;
  email: string;
  status: 'PENDING' | 'EXPIRED' | 'LOCKED' | 'ACTIVATED';
  created_at: string;
  expires_at: string;
}
