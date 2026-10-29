<script lang="ts">
  import { list, t } from '../lib/i18n.svelte'
  import Avatar from '../lib/Avatar.svelte'
  import { firstName } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { Room } from '../lib/types'
  import PlanGrid from './PlanGrid.svelte'
  import { store } from './store.svelte'
  import { voice } from './voice.svelte'

  let note = $state('')
  let quietHint = $state(false)
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
    return list(ids.map((id) => (id === me ? t('common.you') : firstName(store.people[id]?.name ?? t('common.someone')))))
  }

  function meta(room: Room) {
    if (room.kind === 'hallway') {
      if (!mine) return t('plan.you_are_here')
      return hallwayPeople.length ? t('plan.hallway_online') : t('plan.empty')
    }
    const people = live(room)?.people ?? []
    if (!people.length) {
      if (room.kind === 'quiet') return t('plan.quiet_empty')
      if (!room.can_enter) return t('plan.for_channel', { channel: room.channel_name })
      return t('plan.empty')
    }
    if (room.kind === 'quiet') return t('plan.focus', { names: names(people.map((p) => p.user_id)), n: people.length, me: people.some((p) => p.user_id === me) })
    return names(people.map((p) => p.user_id))
  }

  function enter(room: Room) {
    note = ''
    quietHint = false
    if (room.kind === 'hallway') {
      if (mine) leave()
      return
    }
    if (room.kind === 'quiet') {
      const there = (live(room)?.people ?? []).filter((p) => p.user_id !== me).map((p) => p.user_id)
      note = there.length ? t('plan.quiet_busy', { names: names(there), n: there.length }) : t('plan.quiet_free')
      quietHint = true
      return
    }
    if (!room.can_enter) {
      note = t('plan.locked', { channel: room.channel_name })
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
  <div class="floors" role="group" aria-label={t('plan.floors')}>
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
        aria-label={`${r.name}. ${meta(r)}${!r.can_enter && r.kind === 'normal' ? `. ${t('plan.locked_label', { channel: r.channel_name })}` : ''}`}>
        <span class="room-name">{#if !r.can_enter && r.kind === 'normal'}{@html icons.lock(11)}{/if}{r.name}</span>
        <span class="room-meta">{meta(r)}</span>
        {#if st?.notes_by_id}
          <span class="room-notes">{@html icons.pen()} {t('plan.notes_by', { name: firstName(st.notes_by_name) })}</span>
        {/if}
        <span class="people">
          {#if r.kind === 'hallway'}
            {#each hallwayPeople as id (id)}
              {@const person = store.people[id]}
              <Avatar size="s" initials={person?.initials} tone={person?.tone} me={id === me} title={id === me ? t('plan.you_named', { name: person?.name }) : person?.name} />
            {/each}
          {:else}
            {#each st?.people ?? [] as p (p.user_id)}
              {@const person = store.people[p.user_id]}
              <Avatar size="s" initials={person?.initials} tone={person?.tone} me={p.user_id === me} muted={p.muted && r.kind !== 'quiet'}
                talking={voice.speaking.includes(p.user_id)} title={person?.name} arrive={p.user_id === me} />
            {/each}
            {#if st?.notes_by_id}<Avatar kind="agent" size="s" initials="N" title={t('plan.notes_agent')} />{/if}
          {/if}
        </span>
        {#if r.kind !== 'quiet' && r.row + r.row_span < lastRow}<span class="door" style={r.col_span > 1 ? 'left:46%' : r.col > 0 ? 'right:18px' : 'left:18px'}></span>{/if}
      </button>
    {/snippet}
  </PlanGrid>
{/if}

<p class="plan-note" aria-live="polite">
  {#if hallway && hallway.floor_id !== floorId && hallwayPeople.length}
    {t('plan.hallway_elsewhere', { n: hallwayPeople.length, floor: store.floors.find((f) => f.id === hallway.floor_id)?.name })}
  {/if}
  {note}
  {#if note && quietHint && myRoomConfig?.kind !== 'quiet'}
    <button class="link-btn" onclick={goQuiet}>{t('plan.go_quiet')}</button>
  {/if}
</p>

{#if mine && myRoomConfig}
  {@const others = mine.people.map((p) => p.user_id).filter((id) => id !== me)}
  <div class="livebar" aria-live="polite">
    <strong>{t('live.in', { room: myRoomConfig.name })}</strong>
    <p>{t('live.with', { names: names(others), n: others.length })}</p>
    {#if myRoomConfig.kind === 'normal'}
      {#if notesHere}
        <p class="notes-line">{@html icons.pen()}<span>{mine.notes_by_id === me ? t('live.notes_on_me') : t('live.notes_on', { name: firstName(mine.notes_by_name) })}</span></p>
      {:else if myRoomConfig.channel_id}
        <p class="notes-line off"><span>{t('live.notes_off')}</span></p>
      {:else}
        <p class="notes-line off"><span>{t('live.no_notes_room')}</span></p>
      {/if}
      <div class="row">
        <button class="btn small" onclick={toggleMute}>{voice.muted ? t('live.unmute') : t('live.mute')}</button>
        {#if myRoomConfig.channel_id}<button class="btn small" onclick={toggleNotes}>{notesHere ? t('live.notes_off_btn') : t('live.notes_on_btn')}</button>{/if}
        <button class="btn small" onclick={leave}>{t('live.leave')}</button>
      </div>
      <p class="voice">{voice.error ? t(voice.error) : voice.connected ? t('live.voice_on') : t('live.voice_off')}</p>
    {:else}
      <p class="notes-line off"><span>{t('live.quiet')}</span></p>
      <div class="row"><button class="btn small" onclick={leave}>{t('live.leave')}</button></div>
    {/if}
  </div>
{/if}
