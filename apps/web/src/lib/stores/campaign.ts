import { writable } from 'svelte/store';

export const activeCampaignId = writable<string | null>(null);
