<script lang="ts">
  import Avatar from '../lib/Avatar.svelte'
  import { firstName } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { Room } from '../lib/types'
  import PlanGrid from './PlanGrid.svelte'
  import { store } from './store.svelte'
  import { voice } from './voice.svelte'

  let note = $state('')
  let chosen = $state<string | null>(readFloor())

  const me = $derived(store.me?.id ?? '')
  const mine = $derived(store.myRoom)
  const myRoomConfig = $derived(store.rooms.find((r) => r.id === mine?.id))
  const inRoom = $derived(new Set(store.presence.flatMap((r) => r.people.map((p) => p.user_id))))
  const hallwayPeople = $derived(store.online.filter((id) => !inRoom.has(id)))
  const hallway = $derived(store.rooms.find((r) => r.kind === 'hallway'))
  const floorId = $derived(
    (chosen && store.floors.some((f) => f.id === chosen) && chosen) || myRoomConfig?.floor_id || hallway?.floor_id || store.floors[0]?.id,
  )
  const floor = $derived(store.floors.find((f) => f.id === floorId))
  const onFloor = $derived(store.rooms.filter((r) => r.floor_id === floorId))
  const notesHere = $derived(!!mine?.notes_by_id)
  const lastRow = $derived(Math.max(0, ...onFloor.map((r) => r.row + r.row_span)))

  function readFloor() {
    try {
      return localStorage.getItem('atrium.floor')
    } catch {
      return null
    }
  }

  function pickFloor(id: string) {
    chosen = id
    note = ''
    try {
      localStorage.setItem('atrium.floor', id)
    } catch {}
  }

  function live(room: Room) {
    return store.presence.find((r) => r.id === room.id)
  }

  function names(ids: string[]) {
    const n = ids.map((id) => (id === me ? 'you' : firstName(store.people[id]?.name ?? 'Someone')))
    if (n.length <= 1) return n.join('')
    return `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}`
  }

  function meta(room: Room) {
    if (room.kind === 'hallway') {
      if (!mine) return 'You are here'
      return hallwayPeople.length ? 'Online, in no room' : 'Empty'
    }
    const people = live(room)?.people ?? []
    if (!people.length) {
      if (room.kind === 'quiet') return 'Empty, for focused work'
      if (!room.can_enter) return `For #${room.channel_name}`
      return 'Empty'
    }
    if (room.kind === 'quiet') return `${names(people.map((p) => p.user_id))} working with focus`
    return names(people.map((p) => p.user_id))
  }

  function enter(room: Room) {
    note = ''
    if (room.kind === 'hallway') {
      if (mine) leave()
      return
    }
    if (room.kind === 'quiet') {
      const there = (live(room)?.people ?? []).filter((p) => p.user_id !== me).map((p) => p.user_id)
      note = there.length
        ? `${names(there)} ${there.length === 1 ? 'is' : 'are'} working with focus. Better send a message, they'll see it when they come out.`
        : 'The quiet room is for focused work. Nobody can talk to you in there.'
      return
    }
    if (!room.can_enter) {
      note = `Only members of #${room.channel_name} can go in.`
      return
    }
    if (mine?.id === room.id) return
    voice.muted = false
    store.send({ type: 'room.join', room_id: room.id })
  }

  function goQuiet() {
    const q = store.rooms.find((r) => r.kind === 'quiet' && r.floor_id === floorId) ?? store.rooms.find((r) => r.kind === 'quiet')
    if (q) store.send({ type: 'room.join', room_id: q.id })
    note = ''
  }

  function leave() {
    store.send({ type: 'room.leave' })
    voice.leave()
  }

  function toggleMute() {
    const m = !voice.muted
    voice.setMuted(m)
    store.send({ type: 'room.mute', muted: m })
  }

  function toggleNotes() {
    store.send({ type: 'room.notes', on: !notesHere })
  }

  $effect(() => {
    if (notesHere && myRoomConfig?.kind === 'normal') voice.startNotes((c) => store.sendAudio(c))
    else voice.stopNotes()
  })

  $effect(() => {
    if (!mine) voice.leave()
  })
</script>

{#if store.floors.length > 1}
  <div class="floors" role="group" aria-label="Floors">
    {#each store.floors as f (f.id)}
      <button aria-pressed={f.id === floorId} onclick={() => pickFloor(f.id)}>
        {f.name}{#if myRoomConfig?.floor_id === f.id && f.id !== floorId} ·{/if}
      </button>
    {/each}
  </div>
{/if}

{#if floor}
  <PlanGrid {floor} rooms={onFloor}>
    {#snippet room(r, style)}
      {@const st = live(r)}
      {@const lit = (st?.people.length ?? 0) > 0}
      <button class="room" class:tall={r.col_span > 1} class:quiet={r.kind === 'quiet'} class:locked={!r.can_enter && r.kind === 'normal'}
        class:lit={lit || (r.kind === 'hallway' && hallwayPeople.length > 0)} class:here={mine?.id === r.id || (r.kind === 'hallway' && !mine)}
        {style} onclick={() => enter(r)}
        aria-label={`${r.name}. ${meta(r)}${!r.can_enter && r.kind === 'normal' ? `. Only for members of #${r.channel_name}` : ''}`}>
        <span class="room-name">{#if !r.can_enter && r.kind === 'normal'}{@html icons.lock(11)}{/if}{r.name}</span>
        <span class="room-meta">{meta(r)}</span>
        {#if st?.notes_by_id}
          <span class="room-notes">{@html icons.pen()} Notes on, by {firstName(st.notes_by_name)}</span>
        {/if}
        <span class="people">
          {#if r.kind === 'hallway'}
            {#each hallwayPeople as id (id)}
              {@const person = store.people[id]}
              <Avatar size="s" initials={person?.initials} tone={person?.tone} me={id === me} title={id === me ? `You, ${person?.name}` : person?.name} />
            {/each}
          {:else}
            {#each st?.people ?? [] as p (p.user_id)}
              {@const person = store.people[p.user_id]}
              <Avatar size="s" initials={person?.initials} tone={person?.tone} me={p.user_id === me} muted={p.muted && r.kind !== 'quiet'}
                talking={voice.speaking.includes(p.user_id)} title={person?.name} arrive={p.user_id === me} />
            {/each}
            {#if st?.notes_by_id}<Avatar kind="agent" size="s" initials="N" title="Notes agent, taking notes" />{/if}
          {/if}
        </span>
        {#if r.kind !== 'quiet' && r.row + r.row_span < lastRow}<span class="door" style={r.col_span > 1 ? 'left:46%' : r.col > 0 ? 'right:18px' : 'left:18px'}></span>{/if}
      </button>
    {/snippet}
  </PlanGrid>
{/if}

<p class="plan-note" aria-live="polite">
  {#if hallway && hallway.floor_id !== floorId && hallwayPeople.length}
    {hallwayPeople.length} online in the hallway on {store.floors.find((f) => f.id === hallway.floor_id)?.name}.
  {/if}
  {note}
  {#if note && note.includes('focused') && store.rooms.some((r) => r.kind === 'quiet') && myRoomConfig?.kind !== 'quiet'}
    <button class="link-btn" onclick={goQuiet}>Go quiet yourself</button>
  {/if}
</p>

{#if mine && myRoomConfig}
  {@const others = mine.people.map((p) => p.user_id).filter((id) => id !== me)}
  <div class="livebar" aria-live="polite">
    <strong>You're in {myRoomConfig.name}</strong>
    <p>{others.length ? `${names(others)} ${others.length === 1 ? 'is' : 'are'} here.` : 'Nobody else is here yet.'}</p>
    {#if myRoomConfig.kind === 'normal'}
      {#if notesHere}
        <p class="notes-line">{@html icons.pen()}<span>Notes are running, turned on by {mine.notes_by_id === me ? 'you' : firstName(mine.notes_by_name)}. Everyone in the room sees this.</span></p>
      {:else if myRoomConfig.channel_id}
        <p class="notes-line off"><span>No notes. Nothing is recorded here.</span></p>
      {:else}
        <p class="notes-line off"><span>This room has no notes. Nothing is recorded here.</span></p>
      {/if}
      <div class="row">
        <button class="btn small" onclick={toggleMute}>{voice.muted ? 'Unmute' : 'Mute'}</button>
        {#if myRoomConfig.channel_id}<button class="btn small" onclick={toggleNotes}>{notesHere ? 'Notes off' : 'Notes on'}</button>{/if}
        <button class="btn small" onclick={leave}>Leave room</button>
      </div>
      <p class="voice">{voice.error || (voice.connected ? 'Voice connected.' : 'Voice is off on this server.')}</p>
    {:else}
      <p class="notes-line off"><span>Quiet. No voice, no notes.</span></p>
      <div class="row"><button class="btn small" onclick={leave}>Leave room</button></div>
    {/if}
  </div>
{/if}
