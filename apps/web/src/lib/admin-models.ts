import { deleteJson, getJson, patchJson, postJson } from '$lib/api';
import type { AgentRole, CatalogEntry, CatalogEntryPayload } from '$lib/types';

export type CatalogEntryPatch = Partial<Omit<CatalogEntryPayload, 'catalog_id' | 'role'>>;

export async function listCatalog(role?: AgentRole): Promise<CatalogEntry[]> {
  const query = role ? `?role=${role}` : '';
  return getJson<CatalogEntry[]>(`/admin/models${query}`);
}

export async function createEntry(payload: CatalogEntryPayload): Promise<CatalogEntry> {
  return postJson<CatalogEntry>('/admin/models', payload);
}

export async function updateEntry(
  catalogId: string,
  role: AgentRole,
  patch: CatalogEntryPatch
): Promise<CatalogEntry> {
  return patchJson<CatalogEntry>(`/admin/models/${encodeURIComponent(catalogId)}/${role}`, patch);
}

export async function deleteEntry(catalogId: string, role: AgentRole): Promise<void> {
  await deleteJson(`/admin/models/${encodeURIComponent(catalogId)}/${role}`);
}
