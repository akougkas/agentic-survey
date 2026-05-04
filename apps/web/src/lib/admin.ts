import { ApiError, getJson } from '$lib/api';
import type { AdminSessionResponse } from '$lib/types';

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
