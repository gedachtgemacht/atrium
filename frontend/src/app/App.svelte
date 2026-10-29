<script lang="ts">
  import { onMount } from 'svelte'
  import { api, ApiError } from '../lib/api'
  import type { Me } from '../lib/types'
  import Login from './Login.svelte'
  import Shell from './Shell.svelte'
  import { store } from './store.svelte'

  let state = $state<'loading' | 'login' | 'in'>('loading')

  async function check() {
    try {
      store.me = await api<Me>('/api/me')
      document.title = `Atrium · ${store.me.org_name}`
      state = 'in'
      await store.start()
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) state = 'login'
      else state = 'login'
    }
  }

  onMount(check)
</script>

{#if state === 'login'}
  <Login onIn={check} />
{:else if state === 'in'}
  <Shell />
{/if}
