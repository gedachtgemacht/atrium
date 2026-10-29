<script lang="ts">
  import { onMount, tick } from 'svelte'
  import Avatar from '../lib/Avatar.svelte'
  import { dayLabel, firstName } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { Channel } from '../lib/types'
  import Composer from './Composer.svelte'
  import GuestPreview from './GuestPreview.svelte'
  import InviteDialog from './InviteDialog.svelte'
  import MessageItem from './MessageItem.svelte'
  import { store } from './store.svelte'

  let { channel }: { channel: Channel } = $props()
  let feed: HTMLElement | undefined = $state()
  let inviting = $state(false)
  let previewGuest = $state<{ id: string; name: string } | null>(null)

  const detail = $derived(store.details[channel.id])
  const messages = $derived(store.messages[channel.id] ?? [])
  const shared = $derived(channel.kind === 'shared')
  const partner = $derived(channel.partner_name || channel.name)
  const guests = $derived((detail?.guests ?? []).filter((g) => g.joined && !g.revoked_at && new Date(g.expires_at) > new Date()))
  const people = $derived(detail?.members ?? [])

  onMount(async () => {
    await Promise.all([store.loadDetail(channel.id), store.loadMessages(channel.id)])
    store.markRead(channel.id)
    await tick()
    feed?.scrollTo({ top: feed.scrollHeight })
  })

  // Keep the newest message in view when one arrives and we're near the bottom.
  let lastCount = 0
  $effect(() => {
    const n = messages.length
    if (n > lastCount && feed) {
      const near = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 200
      if (near || lastCount === 0) tick().then(() => feed?.scrollTo({ top: feed.scrollHeight, behavior: lastCount ? 'smooth' : 'auto' }))
    }
    lastCount = n
  })

  function newDay(i: number) {
    if (i === 0) return true
    return new Date(messages[i].created_at).toDateString() !== new Date(messages[i - 1].created_at).toDateString()
  }

  function sub() {
    if (channel.description) return channel.description
    if (shared) return `Customer channel with ${partner}. Guests are here by link, without an account.`
    return ''
  }
</script>

<main class="channel" id="shared">
  <div class="chan-head">
    <div>
      <h1>{shared ? channel.name : `#${channel.name}`}</h1>
      {#if sub()}<p class="chan-sub">{sub()}</p>{/if}
      <div class="members">
        <div class="stack" aria-label="Members">
          {#each people as p (p.id)}
            <Avatar kind={p.kind} size="s" initials={p.initials} tone={p.tone} title={p.kind === 'guest' ? `${p.name}, guest` : p.name} />
          {/each}
        </div>
        {#if shared}
          <span class="rule-chip" title="Agents can neither read this channel nor write here.">{@html icons.person()} Only people write here</span>
        {/if}
      </div>
    </div>
    {#if shared}
      <div class="head-actions">
        {#if guests.length === 1}
          <button class="btn" onclick={() => (previewGuest = { id: guests[0].id, name: guests[0].name! })}>{@html icons.eye()} View as {firstName(guests[0].name!)}</button>
        {:else if guests.length > 1}
          <label class="sr" for="viewas">View as guest</label>
          <select id="viewas" class="btn" onchange={(e) => {
            const g = guests.find((x) => x.id === (e.currentTarget as HTMLSelectElement).value)
            if (g) previewGuest = { id: g.id, name: g.name! }
            ;(e.currentTarget as HTMLSelectElement).value = ''
          }}>
            <option value="">View as …</option>
            {#each guests as g (g.id)}<option value={g.id}>{g.name}</option>{/each}
          </select>
        {/if}
        <button class="btn" onclick={() => (inviting = true)}>{@html icons.link()} Invite</button>
        <button class="btn back-toggle" aria-controls="backroom" aria-expanded={store.backroomOpen}
          onclick={() => { store.railOpen = false; store.backroomOpen = !store.backroomOpen }}>{@html icons.lock(14)} Backroom</button>
      </div>
    {/if}
  </div>

  <div class="feed" bind:this={feed} aria-live="polite">
    {#each messages as m, i (m.id)}
      {#if newDay(i)}<div class="day">{dayLabel(m.created_at)}</div>{/if}
      <MessageItem message={m} where={shared ? 'shared' : 'internal'} />
    {:else}
      <p class="empty-feed">No messages yet.</p>
    {/each}
  </div>

  <Composer {channel}
    placeholder={shared ? `Message to ${partner}` : `Message #${channel.name}`}
    hint={shared ? `${partner} reads along here. Agents don't read this channel and don't write here.` : 'Mention an agent like @QuoteAgent to bring it in. It only sees this channel.'} />
</main>

{#if inviting}<InviteDialog {channel} onclose={() => { inviting = false; store.loadDetail(channel.id) }} />{/if}
{#if previewGuest}<GuestPreview guest={previewGuest} onclose={() => (previewGuest = null)} />{/if}
