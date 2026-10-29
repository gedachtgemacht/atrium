<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  import { icons } from '../lib/icons'
  import Admin from './Admin.svelte'
  import Backroom from './Backroom.svelte'
  import ChannelView from './ChannelView.svelte'
  import Rail from './Rail.svelte'
  import SearchBox from './SearchBox.svelte'
  import { store } from './store.svelte'

  const shared = $derived(store.current?.kind === 'shared' ? store.current : null)
  const showBack = $derived(!!shared?.backroom_id && store.route.view === 'channel')

  function closeDrawers() {
    store.railOpen = false
    store.backroomOpen = false
  }
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && closeDrawers()} />

<header class="top">
  <button class="icon-btn menu-btn" aria-label={t('shell.menu')} aria-expanded={store.railOpen}
    onclick={() => { store.backroomOpen = false; store.railOpen = !store.railOpen }}>{@html icons.menu()}</button>
  <a class="brand" href="#/">Atrium <small>{store.me?.org_name}</small></a>
  <SearchBox />
  <div class="trust">
    <span class="chip opt" title={t('shell.trust_title')}>{@html icons.server()}
      {store.me?.server_location ? t('shell.server_at', { place: store.me.server_location }) : t('shell.server')}</span>
    {#if !store.connected}<span class="chip" role="status">{t('shell.reconnecting')}</span>{/if}
  </div>
</header>

<div class="app" class:no-back={!showBack}>
  <Rail />
  {#if store.route.view === 'admin'}
    <Admin />
  {:else if store.current}
    {#key store.current.id}
      <ChannelView channel={store.current} />
      {#if showBack && shared}
        <Backroom {shared} />
      {/if}
    {/key}
  {:else}
    <main class="channel"><p class="empty-feed">{t('shell.pick')}</p></main>
  {/if}
</div>
{#if store.railOpen || store.backroomOpen}
  <div class="scrim" role="presentation" onclick={closeDrawers}></div>
{/if}
{#if store.toastText}<div class="toast" role="status">{store.toastText}</div>{/if}
