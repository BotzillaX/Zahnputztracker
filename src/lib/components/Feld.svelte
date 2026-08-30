<script>
  let { label, hinweis = "", breit = false, children } = $props();
</script>

<label class:breit>
  <span class="beschriftung">{label}</span>
  {@render children()}
  {#if hinweis}<span class="hinweis">{hinweis}</span>{/if}
</label>

<style>
  label { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .breit { grid-column: 1 / -1; }
  .beschriftung { font-size: 12px; color: var(--muted); }
  .hinweis { font-size: 11px; color: var(--muted); }
</style>
