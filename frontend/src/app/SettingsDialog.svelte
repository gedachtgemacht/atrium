<script lang="ts">
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { LANGS, setLanguage, t } from '../lib/i18n.svelte'
  import type { Me } from '../lib/types'
  import { store } from './store.svelte'
  import { applyTheme, getTheme, type Theme } from './theme'

  let { onclose }: { onclose: () => void } = $props()
  let dlg: HTMLDialogElement | undefined = $state()
  let theme = $state<Theme>(getTheme())
  let permission = $state<NotificationPermission | 'unsupported'>('Notification' in window ? Notification.permission : 'unsupported')

  const me = $derived(store.me!)

  onMount(() => dlg?.showModal())

  async function save(body: Partial<Pick<Me, 'locale' | 'notify_email'>>) {
    store.me = await api<Me>('/api/me', { method: 'PATCH', body })
    setLanguage(store.me.language)
    store.loadAgents()
  }

  async function enableBrowser() {
    permission = await Notification.requestPermission()
  }
</script>

<dialog bind:this={dlg} onclose={onclose} aria-labelledby="setTitle">
  <div class="dlg">
    <h2 id="setTitle">{t('settings.title')}</h2>
    <label class="field">{t('settings.language')}
      <select value={me.locale} onchange={(e) => save({ locale: (e.currentTarget as HTMLSelectElement).value })}>
        <option value="">{t('settings.language_default', { name: t(`lang.${me.org_language}`) })}</option>
        {#each LANGS as l}<option value={l}>{t(`lang.${l}`)}</option>{/each}
      </select>
    </label>
    <label class="field">{t('settings.theme')}
      <select bind:value={theme} onchange={() => applyTheme(theme)}>
        <option value="auto">{t('settings.theme_auto')}</option>
        <option value="light">{t('settings.theme_light')}</option>
        <option value="dark">{t('settings.theme_dark')}</option>
      </select>
    </label>
    <label class="check"><input type="checkbox" checked={me.notify_email} onchange={(e) => save({ notify_email: (e.currentTarget as HTMLInputElement).checked })} /> {t('settings.email')}</label>
    <p>{t('settings.email_hint')}</p>
    <div class="field">{t('settings.browser')}
      {#if permission === 'granted'}<p>{t('settings.browser_on')}</p>
      {:else if permission === 'denied'}<p>{t('settings.browser_blocked')}</p>
      {:else if permission === 'unsupported'}<p>{t('settings.browser_none')}</p>
      {:else}<div><button class="btn small" onclick={enableBrowser}>{t('settings.browser_enable')}</button></div>{/if}
    </div>
    <div class="row"><button class="btn primary" onclick={() => dlg?.close()}>{t('common.done')}</button></div>
  </div>
</dialog>
