<script lang="ts">
  import { list, t } from '../lib/i18n.svelte'
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import type { Channel } from '../lib/types'
  import { store } from './store.svelte'

  let { onclose }: { onclose: () => void } = $props()
  let dlg: HTMLDialogElement | undefined = $state()
  let name = $state('')
  let kind = $state<'internal' | 'shared'>('internal')
  let partner = $state('')
  let description = $state('')
  let members = $state<string[]>([])
  let error = $state('')

  const people = $derived(Object.values(store.people).filter((p) => p.id !== store.me?.id))

  onMount(() => dlg?.showModal())

  async function create(e: SubmitEvent) {
    e.preventDefault()
    error = ''
    try {
      const ch = await api<Channel>('/api/channels', {
        body: { name: kind === 'internal' ? name.replace(/^#/, '').trim().toLowerCase() : name.trim(), kind, partner_name: kind === 'shared' ? partner || name : '', description, member_ids: members },
      })
      await store.loadChannels()
      dlg?.close()
      store.go(ch.id)
    } catch (err) {
      error = (err as Error).message
    }
  }
</script>

<dialog bind:this={dlg} onclose={onclose} aria-labelledby="ncTitle">
  <form class="dlg" onsubmit={create}>
    <h2 id="ncTitle">{t('nc.title')}</h2>
    <fieldset class="member-pick" style="border:0;padding:0;margin:0">
      <legend class="sr">{t('nc.kind')}</legend>
      <label><input type="radio" bind:group={kind} value="internal" /> {t('nc.internal')}</label>
      <label><input type="radio" bind:group={kind} value="shared" /> {t('nc.shared')}</label>
    </fieldset>
    {#if kind === 'shared'}<p>{t('nc.shared_hint')}</p>{/if}
    <label class="field">{t('nc.name')}<input bind:value={name} required maxlength="200" placeholder={kind === 'shared' ? 'Hollmann Bau' : 'dispatch'} /></label>
    {#if kind === 'shared'}<label class="field">{t('nc.partner')}<input bind:value={partner} maxlength="200" /></label>{/if}
    <label class="field">{t('nc.description')}<input bind:value={description} maxlength="300" /></label>
    <div class="field">{t('nc.members')}
      <div class="member-pick">
        {#each people as p (p.id)}
          <label><input type="checkbox" bind:group={members} value={p.id} />{p.name}</label>
        {/each}
      </div>
    </div>
    {#if error}<p class="error">{error}</p>{/if}
    <div class="row"><button type="button" class="btn" onclick={() => dlg?.close()}>{t('common.cancel')}</button><button class="btn primary">{t('nc.create')}</button></div>
  </form>
</dialog>
