<script lang="ts">
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { pickLanguage, setLanguage } from '../lib/i18n.svelte'
  import type { Me } from '../lib/types'
  import './i18n'
  import Login from './Login.svelte'
  import Shell from './Shell.svelte'
  import { store } from './store.svelte'
  import { applyTheme } from './theme'

  let state = $state<'loading' | 'login' | 'in'>('loading')
  applyTheme()
  setLanguage(pickLanguage(navigator.language))

  async function check() {
    try {
      store.me = await api<Me>('/api/me')
      setLanguage(store.me.language)
      document.title = `Atrium · ${store.me.org_name}`
      state = 'in'
      await store.start()
    } catch {
      state = 'login'
    }
  }

  onMount(check)
</script>

{#if state === 'login'}
  <Login onIn={check} />
{:else if state === 'in'}
  <Shell />
{/if}
