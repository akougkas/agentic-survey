<script lang="ts">
  export let value = 0.62;
  const degrees = Math.max(0, Math.min(1, value)) * 360;
</script>

<section class="band flex items-center gap-5 px-5 py-5">
  <div
    class="grid h-24 w-24 shrink-0 place-items-center rounded-full border border-[color:var(--line)]"
    style={`background: conic-gradient(var(--moss) ${degrees}deg, rgba(232,224,207,0.08) ${degrees}deg 360deg);`}
  >
    <div class="grid h-16 w-16 place-items-center rounded-full bg-coal text-sm font-mono">
      {Math.round(value * 100)}%
    </div>
  </div>

  <div class="grid gap-2">
    <p class="eyebrow">Coverage</p>
    <h3 class="font-display text-2xl">Objective depth is holding.</h3>
    <p class="m-0 max-w-[26rem] text-sm leading-7 text-[color:var(--muted)]">
      The next question should stay on workflow friction before moving into trust and validation.
    </p>
  </div>
</section>
