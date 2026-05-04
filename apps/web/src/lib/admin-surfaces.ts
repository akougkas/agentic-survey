export const ADMIN_SURFACE_KEYS = [
  'catalog',
  'campaigns',
  'sessions',
  'transcripts',
  'answers',
  'invites',
  'designer',
  'knowledge',
  'graph',
  'models',
  'bundle'
] as const;

export type AdminSurfaceKey = (typeof ADMIN_SURFACE_KEYS)[number];

export interface AdminNavLink {
  href: string;
  label: string;
  surface: AdminSurfaceKey;
}

export const adminLinks = [
  { href: '/admin/campaigns/new', label: 'Catalog', surface: 'catalog' },
  { href: '/admin/campaigns', label: 'Campaigns', surface: 'campaigns' },
  { href: '/admin/models', label: 'Models', surface: 'models' }
] as const satisfies readonly AdminNavLink[];

export function visibleAdminLinks(
  links: readonly AdminNavLink[],
  allowlist: string[] | null | undefined,
  debug: boolean
): AdminNavLink[] {
  if (debug || allowlist == null) {
    return [...links];
  }

  const bySurface = new Map(links.map((link) => [link.surface, link]));
  return allowlist.flatMap((surface) => {
    const link = bySurface.get(surface as AdminSurfaceKey);
    return link ? [link] : [];
  });
}

export function hrefWithDebug(href: string, debug: boolean): string {
  if (!debug) return href;

  const hashIndex = href.indexOf('#');
  const withoutHash = hashIndex >= 0 ? href.slice(0, hashIndex) : href;
  const hash = hashIndex >= 0 ? href.slice(hashIndex) : '';
  const queryIndex = withoutHash.indexOf('?');
  const path = queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash;
  const query = queryIndex >= 0 ? withoutHash.slice(queryIndex + 1) : '';
  const params = new URLSearchParams(query);
  params.set('debug', '1');
  const search = params.toString();
  return `${path}${search ? `?${search}` : ''}${hash}`;
}
