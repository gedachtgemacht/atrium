<script lang="ts">
  import { api, ApiError } from '../lib/api'

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
      error = err instanceof ApiError ? err.message : 'That didn\'t work. Try again.'
    } finally {
      busy = false
    }
  }
</script>

<main class="center">
  <form class="card" onsubmit={submit}>
    <h1>Atrium</h1>
    <p>Sign in with your work account.</p>
    <label class="field">Email<input type="email" autocomplete="username" required bind:value={email} /></label>
    <label class="field">Password<input type="password" autocomplete="current-password" required bind:value={password} /></label>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <button class="btn primary" type="submit" disabled={busy}>Sign in</button>
  </form>
</main>
