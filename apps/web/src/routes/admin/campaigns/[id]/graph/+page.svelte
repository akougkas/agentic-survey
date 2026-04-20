<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onDestroy, onMount, tick } from 'svelte';

  import {
    forceCenter,
    forceCollide,
    forceLink,
    forceManyBody,
    forceSimulation,
    type Simulation,
    type SimulationLinkDatum,
    type SimulationNodeDatum,
  } from 'd3-force';

  import { getAdminSession } from '$lib/admin';
  import { ApiError, getJson } from '$lib/api';
  import type {
    GraphDelta,
    GraphDeltaEdge,
    GraphDeltaNode,
    GraphEdge,
    GraphNode,
    GraphSnapshotResponse,
  } from '$lib/types';

  interface SimNode extends SimulationNodeDatum {
    id: string;
    label: string;
    type: string;
    mention_count: number;
    is_new?: boolean;
  }

  interface SimLink extends SimulationLinkDatum<SimNode> {
    source: string | SimNode;
    target: string | SimNode;
    edge_table: 'mentioned_with' | 'contradicts';
    kind: string;
    confidence: number;
  }

  const WIDTH = 960;
  const HEIGHT = 640;

  let campaignId = '';
  let loading = true;
  let error = '';
  let connectionStatus: 'connecting' | 'live' | 'disconnected' | 'offline' = 'connecting';
  let latestSeq = -1;

  let nodes: SimNode[] = [];
  let links: SimLink[] = [];
  let renderedNodes: SimNode[] = [];
  let renderedLinks: SimLink[] = [];

  let simulation: Simulation<SimNode, SimLink> | null = null;
  let eventSource: EventSource | null = null;

  $: campaignId = $page.params.id ?? '';
  $: loginPath = `/admin/login?next=${encodeURIComponent($page.url.pathname + $page.url.search)}`;

  onMount(async () => {
    try {
      const session = await getAdminSession();
      if (!session?.authenticated) {
        await goto(loginPath);
        return;
      }
      await loadSnapshot();
      await tick();
      startSimulation();
      openStream();
    } catch (caught) {
      error = caught instanceof ApiError ? caught.message : 'Unable to load the graph.';
      loading = false;
    }
  });

  onDestroy(() => {
    if (simulation) {
      simulation.stop();
      simulation = null;
    }
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  });

  async function loadSnapshot(): Promise<void> {
    loading = true;
    error = '';
    try {
      const snapshot = await getJson<GraphSnapshotResponse>(
        `/admin/campaigns/${campaignId}/graph`,
      );
      nodes = snapshot.nodes.map(nodeFromSnapshot);
      links = snapshot.edges.map(linkFromSnapshot);
      latestSeq = snapshot.latest_event_seq;
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        await goto(loginPath);
        return;
      }
      error = caught instanceof ApiError ? caught.message : 'Unable to load the graph.';
    } finally {
      loading = false;
    }
  }

  function nodeFromSnapshot(node: GraphNode): SimNode {
    return {
      id: node.id,
      label: node.label,
      type: node.type,
      mention_count: node.mention_count,
      is_new: false,
    };
  }

  function linkFromSnapshot(edge: GraphEdge): SimLink {
    return {
      source: edge.from_id,
      target: edge.to_id,
      edge_table: edge.edge_table,
      kind: edge.kind,
      confidence: edge.confidence,
    };
  }

  function startSimulation(): void {
    simulation = forceSimulation<SimNode, SimLink>(nodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(links)
          .id((node) => node.id)
          .distance(110)
          .strength(0.4),
      )
      .force('charge', forceManyBody<SimNode>().strength(-220))
      .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
      .force('collide', forceCollide<SimNode>().radius(28))
      .alpha(1)
      .on('tick', () => {
        renderedNodes = [...nodes];
        renderedLinks = [...links];
      });
  }

  function openStream(): void {
    if (typeof EventSource === 'undefined') {
      connectionStatus = 'offline';
      return;
    }
    const url = `/api/campaigns/${campaignId}/stream?since=${latestSeq}`;
    const source = new EventSource(url, { withCredentials: true });
    eventSource = source;
    connectionStatus = 'connecting';
    source.onopen = () => {
      connectionStatus = 'live';
    };
    source.onerror = () => {
      connectionStatus = 'disconnected';
    };
    source.addEventListener('graph_delta', (event) => {
      const message = event as MessageEvent<string>;
      try {
        const payload = JSON.parse(message.data) as GraphDelta;
        applyDelta(payload);
        if (message.lastEventId) {
          const seq = Number.parseInt(message.lastEventId, 10);
          if (!Number.isNaN(seq)) {
            latestSeq = seq;
          }
        }
      } catch (caught) {
        console.error('graph_delta parse failed', caught);
      }
    });
  }

  function applyDelta(delta: GraphDelta): void {
    // d3-force mutates the bound nodes/links arrays in place, adding x/y/vx/vy.
    // Every mutation here preserves the same array identity so the simulation
    // and the SVG stay in lockstep; Svelte reactivity is triggered via the
    // self-assignment (`nodes = nodes`) rather than by replacing the array.
    const existingIds = new Set(nodes.map((node) => node.id));
    let touched = false;

    for (const rawNode of delta.add_nodes) {
      if (existingIds.has(rawNode.id)) continue;
      nodes.push(nodeFromDelta(rawNode));
      existingIds.add(rawNode.id);
      touched = true;
    }

    const existingLinkKeys = new Set(links.map(linkKey));
    for (const rawEdge of delta.add_edges) {
      const link = linkFromDelta(rawEdge);
      const key = linkKey(link);
      if (existingLinkKeys.has(key)) continue;
      links.push(link);
      existingLinkKeys.add(key);
      touched = true;
    }

    if (simulation && touched) {
      simulation.nodes(nodes);
      const linkForce = simulation.force<ReturnType<typeof forceLink<SimNode, SimLink>>>('link');
      linkForce?.links(links);
      simulation.alpha(0.6).restart();
    }

    const lightIds = new Set(delta.light_up);
    if (lightIds.size > 0) {
      for (const node of nodes) {
        if (lightIds.has(node.id)) node.is_new = true;
      }
      nodes = nodes;
    } else if (touched) {
      nodes = nodes;
    }

    setTimeout(() => {
      let dirty = false;
      for (const node of nodes) {
        if (node.is_new) {
          node.is_new = false;
          dirty = true;
        }
      }
      if (dirty) nodes = nodes;
    }, 1600);
  }

  function nodeFromDelta(node: GraphDeltaNode): SimNode {
    return {
      id: node.id,
      label: node.label,
      type: node.type,
      mention_count: 1,
      is_new: true,
    };
  }

  function linkFromDelta(edge: GraphDeltaEdge): SimLink {
    return {
      source: edge.from,
      target: edge.to,
      edge_table: edge.edge_table,
      kind: edge.kind,
      confidence: edge.confidence,
    };
  }

  function linkKey(link: { source: string | SimNode; target: string | SimNode; edge_table: string }): string {
    const from = typeof link.source === 'string' ? link.source : link.source.id;
    const to = typeof link.target === 'string' ? link.target : link.target.id;
    return `${link.edge_table}:${from}->${to}`;
  }

  function linkEndpoints(link: SimLink): { x1: number; y1: number; x2: number; y2: number } | null {
    const source = link.source;
    const target = link.target;
    if (typeof source === 'string' || typeof target === 'string') return null;
    if (source.x == null || source.y == null || target.x == null || target.y == null) return null;
    return { x1: source.x, y1: source.y, x2: target.x, y2: target.y };
  }
</script>

<section class="grid gap-5">
  <div class="flex items-center justify-between">
    <a class="text-sm text-moss" href={`/admin/campaigns/${campaignId}`}>&larr; Back to campaign</a>
    <div class="flex items-center gap-2">
      <span
        class="status-badge"
        data-tone={connectionStatus === 'live' ? 'moss' : 'neutral'}
        data-testid="graph-connection-status"
      >
        {connectionStatus === 'live' ? 'Live' : connectionStatus}
      </span>
      <span class="status-badge" data-tone="neutral">seq {latestSeq}</span>
    </div>
  </div>

  {#if loading}
    <article class="band px-6 py-6 text-sm text-[color:var(--muted)]">Loading graph...</article>
  {:else if error}
    <article class="band px-6 py-6 text-sm text-ember" data-testid="graph-error">{error}</article>
  {:else}
    <section class="band grid gap-4 px-6 py-6">
      <div class="flex items-center justify-between">
        <div class="grid gap-1">
          <p class="eyebrow">Knowledge graph</p>
          <h2 class="section-title">Live concept view</h2>
          <p class="section-copy m-0">
            New concepts pulse when the validator lands them. Co-occurrence edges use the
            default stroke; <span class="text-ember">contradictions</span> draw in ember.
          </p>
        </div>
        <div class="chip-list">
          <span class="chip">{nodes.length} nodes</span>
          <span class="chip">{links.length} edges</span>
        </div>
      </div>

      <div class="border-t border-[color:var(--line)] pt-4">
        <svg
          class="w-full rounded-[8px] border border-[color:var(--line)] bg-[color:var(--surface)]"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label="Knowledge graph"
          data-testid="graph-svg"
        >
          <g data-testid="graph-edges">
            {#each renderedLinks as link}
              {@const endpoints = linkEndpoints(link)}
              {#if endpoints}
                <line
                  x1={endpoints.x1}
                  y1={endpoints.y1}
                  x2={endpoints.x2}
                  y2={endpoints.y2}
                  stroke={link.edge_table === 'contradicts' ? 'var(--ember, #b45309)' : 'var(--line, #94a3b8)'}
                  stroke-opacity={link.edge_table === 'contradicts' ? 0.85 : 0.5}
                  stroke-width={link.edge_table === 'contradicts' ? 2 : 1.25}
                />
              {/if}
            {/each}
          </g>
          <g data-testid="graph-nodes">
            {#each renderedNodes as node (node.id)}
              {#if node.x != null && node.y != null}
                <g transform={`translate(${node.x}, ${node.y})`} data-node-id={node.id}>
                  <circle
                    r={node.is_new ? 14 : 10}
                    fill={node.is_new ? 'var(--moss, #3f6f46)' : 'var(--surface-inset, #e5e7eb)'}
                    stroke="var(--ink, #111827)"
                    stroke-width={1.25}
                    opacity={node.is_new ? 0.9 : 1}
                  >
                    {#if node.is_new}
                      <animate attributeName="r" values="14;18;14" dur="1.2s" repeatCount="1" />
                    {/if}
                  </circle>
                  <text
                    x="14"
                    y="4"
                    font-size="11"
                    fill="var(--text, #111827)"
                    pointer-events="none"
                  >
                    {node.label}
                  </text>
                </g>
              {/if}
            {/each}
          </g>
        </svg>
      </div>

      {#if nodes.length === 0}
        <p class="m-0 text-sm text-[color:var(--muted)]" data-testid="graph-empty">
          No concepts yet. The graph fills in as participants land turns.
        </p>
      {/if}
    </section>
  {/if}
</section>
