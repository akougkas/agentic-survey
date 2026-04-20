import { ApiError, getJson } from '$lib/api';
import type { AdminSessionResponse } from '$lib/types';

export const adminLinks = [
  { href: '/admin/campaigns', label: 'Overview' },
  { href: '/admin/campaigns/new', label: 'New Campaign' },
  { href: '/admin/models', label: 'Models' },
  { href: '/admin/login', label: 'Login' }
] as const;

export async function getAdminSession(): Promise<AdminSessionResponse | null> {
  try {
    return await getJson<AdminSessionResponse>('/admin/session');
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}
