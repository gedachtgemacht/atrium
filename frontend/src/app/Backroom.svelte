<script lang="ts">
  import { onMount, tick } from 'svelte'
  import { icons } from '../lib/icons'
  import type { Channel } from '../lib/types'
  import Composer from './Composer.svelte'
  import MemoryPanel from './MemoryPanel.svelte'
  import MessageItem from './MessageItem.svelte'
  import { store } from './store.svelte'

  let { shared }: { shared: Channel } = $props()
  let body: HTMLElement | undefined = $state()

  const id = $derived(shared.backroom_id!)
  const room = $derived(store.channel(id))
  const messages = $derived(store.messages[id] ?? [])
  const partner = $derived(shared.partner_name || shared.name)
  const working = $derived(store.agents.filter((a) => store.busy[`${a.slug}:${id}`]))

  onMount(async () => {
    await Promise.all([store.loadMessages(id), store.loadMemory(id)])
    store.markRead(id)
    await tick()
    body?.scrollTo({ top: body.scrollHeight })
  })

  let lastCount = 0
  $effect(() => {
    const n = messages.length
    if (n > lastCount && body && lastCount) tick().then(() => body?.scrollTo({ top: body.scrollHeight, behavior: 'smooth' }))
    lastCount = n
  })

  function tab(t: 'work' | 'memory') {
    store.backroomTab = t
  }
</script>

<aside class="backroom" class:open={store.backroomOpen} id="backroom" aria-label="Backroom">
  <div class="back-head">
    <div class="back-title">
      <h2>{@html icons.lock(17)}Backroom</h2>
      <button class="icon-btn back-close" aria-label="Close backroom" onclick={() => (store.backroomOpen = false)}>{@html icons.x(16)}</button>
    </div>
    <p class="back-sub">Only {store.me?.org_name} sees this. Agents work only here and only read what you pull in from the customer channel.</p>
  </div>
  <div class="tabs" role="tablist" aria-label="Backroom">
    <button role="tab" aria-selected={store.backroomTab === 'work'} onclick={() => tab('work')}>Work{#if room?.unread && store.backroomTab !== 'work'} ({room.unread}){/if}</button>
    <button role="tab" aria-selected={store.backroomTab === 'memory'} onclick={() => tab('memory')}>Memory</button>
  </div>

  {#if store.backroomTab === 'work'}
    <div class="back-body" role="tabpanel" bind:this={body}>
      {#each messages as m (m.id)}
        <MessageItem message={m} where="backroom" />
      {:else}
        <p class="empty" style="margin-top:12px">Nothing here yet. Pull a customer message in, or write to the team.</p>
      {/each}
      {#each working as a (a.slug)}
        <p class="thinking"><span class="pulse" aria-hidden="true"></span>{a.name} is working on it</p>
      {/each}
    </div>
    {#if room}
      <Composer channel={room} backroom placeholder="To the team or @Agent"
        hint={`Stays internal. ${partner} sees none of this.${store.agents.length ? ' Agents here: ' + store.agents.filter((a) => a.slug !== 'notes-agent').map((a) => '@' + a.handle).join(', ') + '.' : ''}`} />
    {/if}
  {:else}
    <MemoryPanel channelId={id} {shared} />
  {/if}
</aside>
