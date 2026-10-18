// src/api/client.ts

let currentAccessToken: string | null = localStorage.getItem('gympro_access_token');

export const setAccessToken = (token: string | null) => {
  currentAccessToken = token;
  if (token) {
    localStorage.setItem('gympro_access_token', token);
  } else {
    localStorage.removeItem('gympro_access_token');
  }
};

export const getAccessToken = () => currentAccessToken;

interface RequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: any;
  params?: Record<string, string | number | boolean | undefined>;
}

export interface ApiResponse<T = any> {
  data: T;
  status: number;
  ok: boolean;
}

export async function apiRequest<T = any>(endpoint: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
  let url = endpoint.startsWith('http') ? endpoint : `/api${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

  if (options.params) {
    const searchParams = new URLSearchParams();
    for (const [k, v] of Object.entries(options.params)) {
      if (v !== undefined) {
        searchParams.append(k, String(v));
      }
    }
    const query = searchParams.toString();
    if (query) {
      url += (url.includes('?') ? '&' : '?') + query;
    }
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (currentAccessToken) {
    headers['Authorization'] = `Bearer ${currentAccessToken}`;
  }

  let res = await fetch(url, {
    method: options.method || 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    credentials: 'include', // sends refresh token cookie
  });

  // Handle 401 refresh attempt once
  if (res.status === 401 && !endpoint.includes('/auth/login') && !endpoint.includes('/auth/refresh')) {
    try {
      const refreshRes = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });
      if (refreshRes.ok) {
        const refreshData = await refreshRes.json();
        if (refreshData.access_token) {
          setAccessToken(refreshData.access_token);
          headers['Authorization'] = `Bearer ${refreshData.access_token}`;
          res = await fetch(url, {
            method: options.method || 'GET',
            headers,
            body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
            credentials: 'include',
          });
        }
      } else {
        setAccessToken(null);
      }
    } catch {
      setAccessToken(null);
    }
  }

  const contentType = res.headers.get('content-type') || '';
  let data: any = null;
  if (contentType.includes('application/json')) {
    data = await res.json().catch(() => null);
  } else {
    data = await res.text().catch(() => null);
  }

  if (!res.ok) {
    const error: any = new Error(
      (data && (data.detail?.error || data.detail || data.error)) || `Request failed with status ${res.status}`
    );
    error.status = res.status;
    error.data = data;
    error.response = { status: res.status, data };
    throw error;
  }

  return { data, status: res.status, ok: true };
}

export const client = {
  get: <T = any>(url: string, params?: Record<string, any>) => apiRequest<T>(url, { method: 'GET', params }),
  post: <T = any>(url: string, body?: any) => apiRequest<T>(url, { method: 'POST', body }),
  put: <T = any>(url: string, body?: any) => apiRequest<T>(url, { method: 'PUT', body }),
  patch: <T = any>(url: string, body?: any) => apiRequest<T>(url, { method: 'PATCH', body }),
  delete: <T = any>(url: string) => apiRequest<T>(url, { method: 'DELETE' }),
};

export function friendlyError(e: any): string {
  const code =
    e?.response?.data?.detail?.error ??
    e?.response?.data?.detail ??
    e?.response?.data?.error ??
    e?.message;

  if (typeof code === 'object') {
    return JSON.stringify(code);
  }

  switch (code) {
    case 'ACTION_EXPIRED':
      return 'That confirmation expired. Ask me again and I will set it up.';
    case 'CLASS_FULL':
      return 'That class just filled up. Want me to add you to the waitlist?';
    case 'PRICE_CHANGED':
      return 'The price changed since I showed it. Ask me again to see the new price.';
    case 'COOLING_OFF_ACTIVE':
      return 'This action is temporarily locked during the 24-hour admin cooling-off window.';
    case 'FORBIDDEN':
      return 'You do not have permission to perform this action.';
    case 'CONSENT_REQUIRED':
      return 'Health data consent is required for this guidance. You can enable it in Privacy settings.';
    case 'DOWNGRADE_NOT_ALLOWED':
      return 'Membership downgrades are processed at renewal by gym staff.';
    case 'INVALID_CREDENTIALS':
      return 'Incorrect email or password.';
    case 'ACCOUNT_PENDING_APPROVAL':
      return 'Your trainer account is awaiting administrator review.';
    case 'ACCOUNT_PENDING_ADMIN_CODE':
      return 'Please enter the one-time activation code sent to existing gym administrators.';
    default:
      return `That could not be completed (${typeof code === 'string' ? code : 'unknown error'}). Want me to find alternatives?`;
  }
}
