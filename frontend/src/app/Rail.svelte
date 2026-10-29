<script lang="ts">
  import { api } from '../lib/api'
  import Avatar from '../lib/Avatar.svelte'
  import FloorPlan from './FloorPlan.svelte'
  import NewChannelDialog from './NewChannelDialog.svelte'
  import { store } from './store.svelte'

  const internal = $derived(store.channels.filter((c) => c.kind === 'internal'))
  const shared = $derived(store.channels.filter((c) => c.kind === 'shared'))
  let creating = $state(false)

  function backroomUnread(id: string | null) {
    return id ? (store.channel(id)?.unread ?? 0) : 0
  }

  function isActive(id: string) {
    return store.route.view === 'channel' && store.route.id === id
  }

  async function signOut() {
    await api('/api/auth/logout', { method: 'POST' })
    location.href = '/'
  }
</script>

<nav class="rail" class:open={store.railOpen} id="rail" aria-label="Rooms and channels">
  <section aria-labelledby="roomsTitle">
    <h2 id="roomsTitle">Rooms</h2>
    <p class="hint">Drop in, talk, leave. No meeting needed.</p>
    <p class="hint">Nobody stores who was where and when. Notes only run if someone in the room turns them on.</p>
    <FloorPlan />
  </section>

  <section aria-labelledby="chTitle">
    <h2 id="chTitle">Channels <button aria-label="New channel" title="New channel" onclick={() => (creating = true)}>+</button></h2>
    <ul class="list">
      {#each internal as c (c.id)}
        <li>
          <a href="#/c/{c.id}" class:active={isActive(c.id)} aria-current={isActive(c.id) ? 'page' : undefined}>
            <span class="hash">#</span><span class="grow">{c.name}</span>
            {#if c.unread}<span class="badge">{c.unread}</span>{/if}
          </a>
        </li>
      {/each}
    </ul>
  </section>

  <section aria-labelledby="partnerTitle">
    <h2 id="partnerTitle">With partners</h2>
    <ul class="list">
      {#each shared as c (c.id)}
        {@const n = c.unread + backroomUnread(c.backroom_id)}
        <li>
          <a href="#/c/{c.id}" class:active={isActive(c.id)} aria-current={isActive(c.id) ? 'page' : undefined}>
            <Avatar kind="guest" size="xs" />
            <span class="grow">{c.name}<span class="sub">Customer channel plus backroom</span></span>
            {#if n}<span class="badge">{n}</span>{/if}
          </a>
        </li>
      {:else}
        <li><span class="sub">No shared channels yet.</span></li>
      {/each}
    </ul>
  </section>

  <section aria-labelledby="agentTitle">
    <h2 id="agentTitle">Agents</h2>
    <p class="hint">Work only internally, never in customer channels.</p>
    <ul class="list">
      {#each store.agents as a (a.id)}
        <li>
          <span title={a.description}>
            <Avatar kind="agent" size="xs" />
            <span class="grow">{a.name}<span class="sub">{a.status || `@${a.handle}`}</span></span>
            {#if a.busy || a.waiting}<span class="pulse" aria-hidden="true"></span>{/if}
          </span>
        </li>
      {/each}
    </ul>
  </section>

  <div class="rail-foot">
    {#if store.me?.is_admin}<a class="btn small" href="#/admin">Admin</a>{/if}
    <button class="btn small" onclick={signOut}>Sign out</button>
  </div>
</nav>

{#if creating}<NewChannelDialog onclose={() => (creating = false)} />{/if}
