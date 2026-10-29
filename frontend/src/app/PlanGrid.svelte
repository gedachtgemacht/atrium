<script lang="ts">
  // A floor plan as a grid. Rooms span cells; the gaps between cells draw the walls.
  import type { Snippet } from 'svelte'
  import type { Floor, Room } from '../lib/types'

  let {
    floor,
    rooms,
    room,
    empty,
  }: { floor: Floor; rooms: Room[]; room: Snippet<[Room, string]>; empty?: Snippet<[number, number]> } = $props()

  const rows = $derived(Math.max(1, ...rooms.map((r) => r.row + r.row_span)) + (empty ? 1 : 0))
  const free = $derived.by(() => {
    const taken = new Set<string>()
    for (const r of rooms)
      for (let c = r.col; c < r.col + r.col_span; c++) for (let w = r.row; w < r.row + r.row_span; w++) taken.add(`${c}:${w}`)
    const out: [number, number][] = []
    for (let w = 0; w < rows; w++) for (let c = 0; c < floor.columns; c++) if (!taken.has(`${c}:${w}`)) out.push([c, w])
    return out
  })

  function place(r: { col: number; row: number; col_span?: number; row_span?: number }) {
    return `grid-column:${r.col + 1} / span ${r.col_span ?? 1};grid-row:${r.row + 1} / span ${r.row_span ?? 1}`
  }
</script>

<div class="plan" style="--cols:{floor.columns}">
  {#each rooms as r (r.id)}
    {@render room(r, place(r))}
  {/each}
  {#each free as [c, w] (`${c}:${w}`)}
    {#if empty}
      {@render empty(c, w)}
    {:else}
      <div class="plan-empty" style={place({ col: c, row: w })} aria-hidden="true"></div>
    {/if}
  {/each}
</div>
