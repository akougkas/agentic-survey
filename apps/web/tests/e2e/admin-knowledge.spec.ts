import { expect, test, type Page, type Route } from '@playwright/test';

import type {
  KnowledgeSourceSummary,
  KnowledgeSourceTimeline,
} from '../../src/lib/types';

const ADMIN_PASSWORD = 'change-me';

async function adminLogin(page: Page): Promise<void> {
  const response = await page.request.post('/api/admin/login', {
    data: { password: ADMIN_PASSWORD },
  });
  expect(response.ok(), `admin login failed: ${response.status()}`).toBeTruthy();
}

async function createSeededCampaign(page: Page): Promise<string> {
  const catalog = await page.request.get('/api/campaigns/catalog');
  expect(catalog.ok()).toBeTruthy();
  const body = (await catalog.json()) as { seeds: Array<{ slug: string }> };
  const seedSlug = body.seeds[0]?.slug;
  expect(seedSlug, 'bundle seed should exist').toBeTruthy();

  const created = await page.request.post('/api/campaigns/from-seed', {
    data: { seed_slug: seedSlug },
  });
  expect(created.ok()).toBeTruthy();
  const payload = (await created.json()) as { id: string };
  return payload.id;
}

test.describe('Admin Knowledge panel', () => {
  test('search → candidates → approve → queue picks up the new source', async ({ page }) => {
    await adminLogin(page);
    const campaignId = await createSeededCampaign(page);

    // Baseline ingestion snapshot the page will load on mount. The seeded
    // campaign has one bundle_seed in pending_approval; nothing in flight yet.
    const seedRow: KnowledgeSourceSummary = {
      source: {
        id: 'ksrc-bundle-seed',
        campaign_id: campaignId,
        kind: 'bundle_seed',
        title: 'Seeded grounding primer',
        url: null,
        hash: 'seed-hash',
        status: 'pending_approval',
        rationale: '',
        approved_at: null,
        approved_by: null,
        error_detail: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      chunk_count: 1,
    };
    let knowledgeStub: KnowledgeSourceTimeline = {
      campaign_id: campaignId,
      total: 1,
      by_status: { pending_approval: [seedRow] },
    };

    await page.route(`**/api/admin/campaigns/${campaignId}/knowledge`, async (route: Route) => {
      if (route.request().method() !== 'GET') {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(knowledgeStub),
      });
    });

    const searchResponse = {
      campaign_id: campaignId,
      query: 'qualitative interview saturation',
      results: [
        {
          title: 'Saturation in qualitative research',
          url: 'https://example.org/saturation',
          snippet: 'An overview of when to stop interviewing.',
          source: 'searxng',
        },
        {
          title: 'Concept saturation thresholds',
          url: 'https://example.org/thresholds',
          snippet: 'Heuristics for deciding n.',
          source: 'searxng',
        },
      ],
      created_source_ids: ['ksrc-candidate-1', 'ksrc-candidate-2'],
    };

    const suggestionRow: KnowledgeSourceSummary = {
      source: {
        id: 'ksrc-candidate-1',
        campaign_id: campaignId,
        kind: 'searxng_suggestion',
        title: 'Saturation in qualitative research',
        url: 'https://example.org/saturation',
        hash: 'hash-1',
        status: 'pending_approval',
        rationale: 'query: qualitative interview saturation',
        approved_at: null,
        approved_by: null,
        error_detail: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      chunk_count: 0,
    };

    await page.route(
      `**/api/admin/campaigns/${campaignId}/knowledge/search`,
      async (route: Route) => {
        // When the search runs, the knowledge timeline should now include a
        // searxng_suggestion row in pending_approval so the poll refresh
        // lands it in both the Mira-proposed and ingestion queue sections.
        knowledgeStub = {
          campaign_id: campaignId,
          total: 2,
          by_status: {
            pending_approval: [
              ...(knowledgeStub.by_status.pending_approval ?? []),
              suggestionRow,
            ],
          },
        };
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(searchResponse),
        });
      },
    );

    await page.route(
      `**/api/admin/campaigns/${campaignId}/knowledge/ksrc-candidate-1/approve`,
      async (route: Route) => {
        // Move the suggestion into the approved bucket and drop it from
        // pending_approval so the UI reflects the approval.
        const approvedRow: KnowledgeSourceSummary = {
          source: {
            ...suggestionRow.source,
            status: 'approved',
            rationale: '',
            approved_at: new Date().toISOString(),
            approved_by: 'scientist',
          },
          chunk_count: 0,
        };
        knowledgeStub = {
          campaign_id: campaignId,
          total: 2,
          by_status: {
            pending_approval: [seedRow],
            approved: [approvedRow],
          },
        };
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            source: approvedRow.source,
            chunk_count: 0,
          }),
        });
      },
    );

    await page.goto(`/admin/campaigns/${campaignId}`);
    await expect(page.getByTestId('knowledge-panel')).toBeVisible();

    // Run the search.
    await page.getByTestId('knowledge-search-input').fill('qualitative interview saturation');
    await page.getByTestId('knowledge-search-submit').click();

    const candidates = page.getByTestId('knowledge-candidate');
    await expect(candidates).toHaveCount(2);
    await expect(page.getByTestId('knowledge-search-status')).toContainText('Queued 2 candidate');

    // The poll refresh should pick up the new searxng_suggestion in the
    // Mira-proposed section.
    const suggestion = page.getByTestId('knowledge-suggestion').first();
    await expect(suggestion).toBeVisible();
    await expect(suggestion).toContainText('Saturation in qualitative research');

    // Approve the suggestion; the ingestion timeline should update to show it
    // under approved grounding on the next poll tick.
    await suggestion.getByTestId('knowledge-approve').click();
    await expect(page.getByText('Approved grounding')).toBeVisible();
    await expect(page.locator('.status-badge[data-tone="moss"]').first()).toContainText('approved');
  });

  test('empty search result renders a "No results" status', async ({ page }) => {
    await adminLogin(page);
    const campaignId = await createSeededCampaign(page);

    await page.route(
      `**/api/admin/campaigns/${campaignId}/knowledge/search`,
      async (route: Route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            campaign_id: campaignId,
            query: 'nonexistent topic',
            results: [],
            created_source_ids: [],
          }),
        });
      },
    );

    await page.goto(`/admin/campaigns/${campaignId}`);
    await expect(page.getByTestId('knowledge-panel')).toBeVisible();

    await page.getByTestId('knowledge-search-input').fill('nonexistent topic');
    await page.getByTestId('knowledge-search-submit').click();

    await expect(page.getByTestId('knowledge-search-status')).toHaveText('No results returned.');
    await expect(page.getByTestId('knowledge-candidate')).toHaveCount(0);
  });

  test('unauthenticated request redirects to admin login', async ({ page, context }) => {
    // Wipe any cookies from previous tests.
    await context.clearCookies();

    await page.goto('/admin/campaigns/campaign-missing');
    await expect(page).toHaveURL(/\/admin\/login/);
  });
});
