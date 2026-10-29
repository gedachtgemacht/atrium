<script lang="ts">
  // Shape the floor plans to the company: floors or sites, rooms on a grid, who may go in, where notes go.
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { icons } from '../lib/icons'
  import type { Floor, Room, RoomsPlan } from '../lib/types'
  import PlanGrid from './PlanGrid.svelte'
  import { store } from './store.svelte'

  type Form = { id: string | null; name: string; kind: string; floor_id: string; col: number; row: number; col_span: number; row_span: number; channel_id: string | null; members_only: boolean }
  type ChannelRow = { id: string; kind: string; name: string }

  let plan = $state<RoomsPlan>({ floors: [], rooms: [] })
  let channels = $state<ChannelRow[]>([])
  let floorId = $state('')
  let form = $state<Form | null>(null)
  let floorsDraft = $state<Floor[]>([])
  let error = $state('')
  let saved = $state('')

  const floor = $derived(plan.floors.find((f) => f.id === floorId) ?? plan.floors[0])
  const onFloor = $derived(plan.rooms.filter((r) => r.floor_id === floor?.id))
  const internal = $derived(channels.filter((c) => c.kind === 'internal'))
  const hasHallway = $derived(plan.rooms.some((r) => r.kind === 'hallway' && r.id !== form?.id))

  onMount(async () => {
    const [p, ch] = await Promise.all([api<RoomsPlan>('/api/admin/rooms'), api<ChannelRow[]>('/api/admin/channels')])
    apply(p)
    channels = ch
  })

  function apply(p: RoomsPlan) {
    plan = p
    store.setPlan(p)
    floorsDraft = p.floors.map((f) => ({ ...f }))
    if (!p.floors.some((f) => f.id === floorId)) floorId = p.floors[0]?.id ?? ''
  }

  function done(text: string) {
    saved = text
    error = ''
    setTimeout(() => (saved = ''), 2500)
  }

  function edit(r: Room) {
    form = { id: r.id, name: r.name, kind: r.kind, floor_id: r.floor_id, col: r.col, row: r.row, col_span: r.col_span, row_span: r.row_span, channel_id: r.channel_id, members_only: r.members_only }
    error = ''
  }

  async function cell(col: number, row: number) {
    error = ''
    if (form?.id) {
      // A room is selected: move it here.
      form.col = col
      form.row = row
      form.floor_id = floor!.id
      await save()
      return
    }
    form = { id: null, name: '', kind: 'normal', floor_id: floor!.id, col, row, col_span: 1, row_span: 1, channel_id: null, members_only: false }
  }

  async function save(e?: SubmitEvent) {
    e?.preventDefault()
    if (!form) return
    const body = { ...form, col_span: Number(form.col_span), row_span: Number(form.row_span), col: Number(form.col), row: Number(form.row) }
    if (body.kind !== 'normal') {
      body.channel_id = null
      body.members_only = false
    }
    if (!body.channel_id) body.members_only = false
    try {
      const p = form.id
        ? await api<RoomsPlan>(`/api/admin/rooms/${form.id}`, { method: 'PUT', body })
        : await api<RoomsPlan>('/api/admin/rooms', { body })
      apply(p)
      const r = p.rooms.find((x) => x.name === body.name)
      if (r) edit(r)
      done('Saved')
    } catch (err) {
      error = (err as Error).message
    }
  }

  let confirmDelete = $state(false)
  async function remove() {
    if (!form?.id) return
    if (!confirmDelete) {
      confirmDelete = true
      setTimeout(() => (confirmDelete = false), 4000)
      return
    }
    confirmDelete = false
    try {
      apply(await api<RoomsPlan>(`/api/admin/rooms/${form.id}`, { method: 'DELETE' }))
      form = null
      done('Room deleted. Anyone inside is back in the hallway.')
    } catch (err) {
      error = (err as Error).message
    }
  }

  async function saveFloors(e?: SubmitEvent) {
    e?.preventDefault()
    try {
      apply(await api<RoomsPlan>('/api/admin/floors', { method: 'PUT', body: { floors: floorsDraft.map((f) => ({ ...f, columns: Number(f.columns) })) } }))
      done('Floors saved')
    } catch (err) {
      error = (err as Error).message
    }
  }

  function addFloor() {
    floorsDraft.push({ id: '', name: `Floor ${floorsDraft.length + 1}`, columns: 2 })
  }
</script>

<p class="hint">Rebuild your office: floors or sites, rooms on a grid, a quiet room, the hallway. Rooms linked to a channel can take notes into it, and can be limited to that channel's members. Who is in a room is never stored.</p>
{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if saved}<p class="saved" role="status">{saved}</p>{/if}

<h2>Floors and sites</h2>
<form onsubmit={saveFloors}>
  <ul class="floor-list">
    {#each floorsDraft as f, i (i)}
      <li>
        <label class="sr" for="fn-{i}">Floor {i + 1} name</label>
        <input id="fn-{i}" bind:value={f.name} required maxlength="100" />
        <label class="sr" for="fc-{i}">Floor {i + 1} columns</label>
        <input id="fc-{i}" type="number" min="1" max="6" bind:value={f.columns} title="Columns" />
        <span class="hint" style="margin:0">columns</span>
        {#if floorsDraft.length > 1}
          <button type="button" class="btn small" onclick={() => floorsDraft.splice(i, 1)} aria-label="Remove {f.name}">{@html icons.trash()}</button>
        {/if}
      </li>
    {/each}
  </ul>
  <div class="row" style="display:flex;gap:8px"><button type="button" class="btn small" onclick={addFloor}>Add floor or site</button><button class="btn small primary">Save floors</button></div>
</form>

<h2>Rooms</h2>
{#if plan.floors.length > 1}
  <div class="floors" role="group" aria-label="Floor to edit">
    {#each plan.floors as f (f.id)}
      <button aria-pressed={f.id === floor?.id} onclick={() => { floorId = f.id; form = null }}>{f.name}</button>
    {/each}
  </div>
{/if}
<div class="rooms-editor">
  <div>
    {#if floor}
      <PlanGrid {floor} rooms={onFloor}>
        {#snippet room(r, style)}
          <button class="room" class:quiet={r.kind === 'quiet'} class:selected={form?.id === r.id} {style} onclick={() => edit(r)}>
            <span class="room-name">{#if r.members_only}{@html icons.lock(11)}{/if}{r.name}</span>
            <span class="room-meta">{r.kind === 'hallway' ? 'Hallway' : r.kind === 'quiet' ? 'Quiet room' : r.channel_name ? `Notes to #${r.channel_name}` : 'No notes'}</span>
          </button>
        {/snippet}
        {#snippet empty(c, w)}
          <button class="plan-empty" style="grid-column:{c + 1};grid-row:{w + 1}" onclick={() => cell(c, w)}
            aria-label={form?.id ? `Move ${form.name} here` : 'New room here'}>{form?.id ? 'Move here' : '+'}</button>
        {/snippet}
      </PlanGrid>
      <p class="hint" style="margin-top:8px">Click a free cell to add a room. Select a room, then click a free cell to move it.</p>
    {/if}
  </div>

  {#if form}
    <form onsubmit={save} aria-label={form.id ? `Edit ${form.name}` : 'New room'}>
      <h3 style="margin:0;font-size:15px">{form.id ? form.name || 'Room' : 'New room'}</h3>
      <label class="field">Name<input bind:value={form.name} required maxlength="100" /></label>
      <label class="field">Kind
        <select bind:value={form.kind}>
          <option value="normal">Talk room (voice, notes)</option>
          <option value="quiet">Quiet room (focus, no voice)</option>
          {#if !hasHallway || form.kind === 'hallway'}<option value="hallway">Hallway (everybody online in no room)</option>{/if}
        </select>
      </label>
      {#if form.kind === 'normal'}
        <label class="field">Notes go to
          <select bind:value={form.channel_id}>
            <option value={null}>No notes in this room</option>
            {#each internal as c (c.id)}<option value={c.id}>#{c.name}</option>{/each}
          </select>
        </label>
        <label class="check"><input type="checkbox" bind:checked={form.members_only} disabled={!form.channel_id} /> Only members of that channel can go in</label>
      {/if}
      <div class="row">
        <label class="field">Floor
          <select bind:value={form.floor_id}>{#each plan.floors as f (f.id)}<option value={f.id}>{f.name}</option>{/each}</select>
        </label>
        <label class="field">Width<input type="number" min="1" max="6" bind:value={form.col_span} /></label>
        <label class="field">Height<input type="number" min="1" max="4" bind:value={form.row_span} /></label>
      </div>
      <div class="row">
        <label class="field">Column<input type="number" min="1" max="6" value={form.col + 1} oninput={(e) => (form!.col = Number((e.currentTarget as HTMLInputElement).value) - 1)} /></label>
        <label class="field">Row<input type="number" min="1" max="12" value={form.row + 1} oninput={(e) => (form!.row = Number((e.currentTarget as HTMLInputElement).value) - 1)} /></label>
      </div>
      <div class="row">
        <button class="btn primary">{form.id ? 'Save room' : 'Add room'}</button>
        <button type="button" class="btn" onclick={() => (form = null)}>Close</button>
        {#if form.id}<button type="button" class="btn danger" onclick={remove}>{confirmDelete ? 'Really delete?' : 'Delete room'}</button>{/if}
      </div>
    </form>
  {/if}
</div>
