import { getJson } from '$lib/api';
import type { AgentRole, BundleCatalogResponse, CatalogEntry } from '$lib/types';

export async function getBundleCatalog(): Promise<BundleCatalogResponse> {
  return getJson<BundleCatalogResponse>('/campaigns/catalog');
}

export async function getModelCatalog(role?: AgentRole): Promise<CatalogEntry[]> {
  const query = role ? `?role=${role}` : '';
  return getJson<CatalogEntry[]>(`/campaigns/model-catalog${query}`);
}
