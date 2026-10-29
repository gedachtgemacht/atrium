<script lang="ts">
  import Avatar from '../lib/Avatar.svelte'
  import { firstName } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { Room } from '../lib/types'
  import { store } from './store.svelte'
  import { voice } from './voice.svelte'

  const layouts = ['dispatch', 'sales', 'warehouse', 'quiet']
  const doors: Record<string, string> = { dispatch: 'left:46%', sales: 'left:18px', warehouse: 'right:18px' }
  let note = $state('')

  const me = $derived(store.me?.id ?? '')
  const mine = $derived(store.myRoom)
  const inRoom = $derived(new Set(store.presence.flatMap((r) => r.people.map((p) => p.user_id))))
  const hallway = $derived(store.online.filter((id) => !inRoom.has(id)))
  const ordered = $derived([...store.rooms].sort((a, b) => a.position - b.position))
  const notesHere = $derived(!!mine?.notes_by_id)
  const myRoomConfig = $derived(store.rooms.find((r) => r.id === mine?.id))

  function roomState(room: Room) {
    return store.presence.find((r) => r.id === room.id)
  }

  function names(ids: string[]) {
    const n = ids.map((id) => (id === me ? 'you' : firstName(store.people[id]?.name ?? 'Someone')))
    if (n.length <= 1) return n.join('')
    return `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}`
  }

  function meta(room: Room) {
    const people = roomState(room)?.people ?? []
    if (!people.length) return room.kind === 'quiet' ? 'Empty, for focused work' : 'Empty'
    if (room.kind === 'quiet') return `${names(people.map((p) => p.user_id))} working with focus`
    return names(people.map((p) => p.user_id))
  }

  function enter(room: Room) {
    note = ''
    if (room.kind === 'quiet') {
      const there = (roomState(room)?.people ?? []).filter((p) => p.user_id !== me).map((p) => p.user_id)
      note = there.length
        ? `${names(there)} ${there.length === 1 ? 'is' : 'are'} working with focus. Better send a message, they'll see it when they come out.`
        : 'The quiet room is for focused work. Nobody can talk to you in there.'
      return
    }
    if (mine?.id === room.id) return
    voice.muted = false
    store.send({ type: 'room.join', room_id: room.id })
  }

  function goQuiet() {
    const q = store.rooms.find((r) => r.kind === 'quiet')
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

<div class="plan">
  {#each ordered as room (room.id)}
    {@const st = roomState(room)}
    {@const lit = (st?.people.length ?? 0) > 0}
    {@const cls = layouts.includes(room.layout) ? `r-${room.layout}` : 'r-extra'}
    <button class="room {cls}" class:lit class:here={mine?.id === room.id} aria-disabled={room.kind === 'quiet' ? 'true' : undefined}
      onclick={() => enter(room)} aria-label={`${room.name}. ${meta(room)}`}>
      <span class="room-name">{room.name}</span>
      <span class="room-meta">{meta(room)}</span>
      {#if st?.notes_by_id}
        <span class="room-notes">{@html icons.pen()} Notes on, by {firstName(st.notes_by_name)}</span>
      {/if}
      <span class="people">
        {#each st?.people ?? [] as p (p.user_id)}
          {@const person = store.people[p.user_id]}
          <Avatar size="s" initials={person?.initials} tone={person?.tone} me={p.user_id === me} muted={p.muted && room.kind !== 'quiet'}
            talking={voice.speaking.includes(p.user_id)} title={person?.name} arrive={p.user_id === me} />
        {/each}
        {#if st?.notes_by_id}<Avatar kind="agent" size="s" initials="N" title="Notes agent, taking notes" />{/if}
      </span>
      {#if doors[room.layout]}<span class="door" style={doors[room.layout]}></span>{/if}
    </button>
  {/each}
  <div class="room r-lobby">
    <span class="room-name">Hallway</span>
    <span class="room-meta">{mine ? (hallway.length ? 'Online, in no room' : 'Empty') : 'You are here'}</span>
    <span class="people">
      {#each hallway as id (id)}
        {@const person = store.people[id]}
        <Avatar size="s" initials={person?.initials} tone={person?.tone} me={id === me} title={id === me ? `You, ${person?.name}` : person?.name} />
      {/each}
    </span>
  </div>
</div>
<p class="plan-note" aria-live="polite">
  {note}
  {#if note && store.rooms.some((r) => r.kind === 'quiet') && myRoomConfig?.kind !== 'quiet'}
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
      {:else}
        <p class="notes-line off"><span>No notes. Nothing is recorded here.</span></p>
      {/if}
      <div class="row">
        <button class="btn small" onclick={toggleMute}>{voice.muted ? 'Unmute' : 'Mute'}</button>
        <button class="btn small" onclick={toggleNotes}>{notesHere ? 'Notes off' : 'Notes on'}</button>
        <button class="btn small" onclick={leave}>Leave room</button>
      </div>
      <p class="voice">{voice.error || (voice.connected ? 'Voice connected.' : 'Voice is off on this server.')}</p>
    {:else}
      <p class="notes-line off"><span>Quiet. No voice, no notes.</span></p>
      <div class="row"><button class="btn small" onclick={leave}>Leave room</button></div>
    {/if}
  </div>
{/if}
