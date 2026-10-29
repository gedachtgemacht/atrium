<script lang="ts">
  import { api, ApiError } from '../lib/api'
  import { t } from '../lib/i18n.svelte'

  let { onIn }: { onIn: () => void } = $props()
  let email = $state('')
  let password = $state('')
  let error = $state('')
  let busy = $state(false)

  async function submit(e: SubmitEvent) {
    e.preventDefault()
    error = ''
    busy = true
    try {
      await api('/api/auth/login', { body: { email, password } })
      onIn()
    } catch (err) {
      error = err instanceof ApiError && err.status === 401 ? t('login.wrong') : t('login.failed')
    } finally {
      busy = false
    }
  }
</script>

<main class="center">
  <form class="card" onsubmit={submit}>
    <h1>Atrium</h1>
    <p>{t('login.intro')}</p>
    <label class="field">{t('login.email')}<input type="email" autocomplete="username" required bind:value={email} /></label>
    <label class="field">{t('login.password')}<input type="password" autocomplete="current-password" required bind:value={password} /></label>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <button class="btn primary" type="submit" disabled={busy}>{t('login.submit')}</button>
  </form>
</main>
