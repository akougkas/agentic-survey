import type { LayoutLoad } from './$types';

import type { RuntimeContextResponse } from '$lib/types';

export const load: LayoutLoad = async ({ fetch }) => {
  try {
    const response = await fetch('/api/system/context');
    if (!response.ok) {
      return { runtimeContext: null };
    }
    return {
      runtimeContext: (await response.json()) as RuntimeContextResponse
    };
  } catch {
    return { runtimeContext: null };
  }
};
