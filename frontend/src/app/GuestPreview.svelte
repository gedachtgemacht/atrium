<script lang="ts">
  import { list, t } from '../lib/i18n.svelte'
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { icons } from '../lib/icons'

  let { guest, onclose }: { guest: { id: string; name: string }; onclose: () => void } = $props()
  let src = $state('')
  let back: HTMLButtonElement | undefined = $state()

  // The preview loads the real guest app against the real guest API, read only.
  onMount(async () => {
    const { token } = await api<{ token: string }>(`/api/guests/${guest.id}/preview`, { method: 'POST' })
    src = `/g/preview#preview=${encodeURIComponent(token)}`
    back?.focus()
  })
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

<div class="preview" role="dialog" aria-label={t('preview.label')}>
  <div class="guest-banner">
    <span>{@html icons.eye(16)}<span><strong>{t('preview.title')}</strong> {t('preview.banner', { name: guest.name })}</span></span>
    <button class="btn small" bind:this={back} onclick={onclose}>{t('preview.back')}</button>
  </div>
  {#if src}<iframe title={t('preview.frame', { name: guest.name })} {src}></iframe>{/if}
</div>
