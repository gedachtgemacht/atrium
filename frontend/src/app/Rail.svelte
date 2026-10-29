<script lang="ts">
  import { api } from '../lib/api'
  import Avatar from '../lib/Avatar.svelte'
  import { list, t } from '../lib/i18n.svelte'
  import type { Agent } from '../lib/types'
  import FloorPlan from './FloorPlan.svelte'
  import NewChannelDialog from './NewChannelDialog.svelte'
  import SettingsDialog from './SettingsDialog.svelte'
  import { store } from './store.svelte'

  const internal = $derived(store.channels.filter((c) => c.kind === 'internal'))
  const shared = $derived(store.channels.filter((c) => c.kind === 'shared'))
  let creating = $state(false)
  let settings = $state(false)

  function backroomUnread(id: string | null) {
    return id ? (store.channel(id)?.unread ?? 0) : 0
  }

  function isActive(id: string) {
    return store.route.view === 'channel' && store.route.id === id
  }

  function status(a: Agent) {
    if (a.role === 'notes') return a.notes_rooms.length ? t('agent.notes_in', { rooms: list(a.notes_rooms) }) : t('agent.notes_none')
    if (a.busy) return t('agent.working')
    if (a.drafts_waiting) return t('agent.draft_waiting', { n: a.drafts_waiting })
    if (a.results_waiting) return t('agent.result_waiting', { n: a.results_waiting })
    return `@${a.handle}`
  }

  async function signOut() {
    await api('/api/auth/logout', { method: 'POST' })
    location.href = '/'
  }
</script>

<nav class="rail" class:open={store.railOpen} id="rail" aria-label={t('rail.label')}>
  <section aria-labelledby="roomsTitle">
    <h2 id="roomsTitle">{t('rail.rooms')}</h2>
    <p class="hint">{t('rail.rooms_hint')}</p>
    <p class="hint">{t('rail.rooms_privacy')}</p>
    <FloorPlan />
  </section>

  <section aria-labelledby="chTitle">
    <h2 id="chTitle">{t('rail.channels')} <button aria-label={t('rail.new_channel')} title={t('rail.new_channel')} onclick={() => (creating = true)}>+</button></h2>
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
    <h2 id="partnerTitle">{t('rail.partners')}</h2>
    <ul class="list">
      {#each shared as c (c.id)}
        {@const n = c.unread + backroomUnread(c.backroom_id)}
        <li>
          <a href="#/c/{c.id}" class:active={isActive(c.id)} aria-current={isActive(c.id) ? 'page' : undefined}>
            <Avatar kind="guest" size="xs" />
            <span class="grow">{c.name}<span class="sub">{t('rail.partner_sub')}</span></span>
            {#if n}<span class="badge">{n}</span>{/if}
          </a>
        </li>
      {:else}
        <li><span class="sub">{t('rail.no_partners')}</span></li>
      {/each}
    </ul>
  </section>

  <section aria-labelledby="agentTitle">
    <h2 id="agentTitle">{t('rail.agents')}</h2>
    <p class="hint">{t('rail.agents_hint')}</p>
    <ul class="list">
      {#each store.agents as a (a.id)}
        <li>
          <span title={a.description}>
            <Avatar kind="agent" size="xs" />
            <span class="grow">{a.name}<span class="sub">{status(a)}</span></span>
            {#if a.busy || a.drafts_waiting || a.results_waiting}<span class="pulse" aria-hidden="true"></span>{/if}
          </span>
        </li>
      {/each}
    </ul>
  </section>

  <div class="rail-foot">
    <button class="btn small" onclick={() => (settings = true)}>{t('rail.settings')}</button>
    {#if store.me?.is_admin}<a class="btn small" href="#/admin">{t('rail.admin')}</a>{/if}
    <button class="btn small" onclick={signOut}>{t('rail.sign_out')}</button>
  </div>
</nav>

{#if creating}<NewChannelDialog onclose={() => (creating = false)} />{/if}
{#if settings}<SettingsDialog onclose={() => (settings = false)} />{/if}
