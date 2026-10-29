<script lang="ts">
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { when } from '../lib/format'
  import type { Channel, GuestInfo } from '../lib/types'
  import { store } from './store.svelte'

  let { channel, onclose }: { channel: Channel; onclose: () => void } = $props()
  let dlg: HTMLDialogElement | undefined = $state()
  let company = $state('')
  let name = $state('')
  let days = $state(90)
  let link = $state('')
  let busy = $state(false)

  const guests = $derived(store.details[channel.id]?.guests ?? [])

  onMount(() => {
    company = channel.partner_name
    dlg?.showModal()
  })

  async function create(e: SubmitEvent) {
    e.preventDefault()
    busy = true
    try {
      const r = await api<{ link: string; guest: GuestInfo }>(`/api/channels/${channel.id}/guests`, {
        body: { company, name, expires_in_days: days },
      })
      link = r.link
      await store.loadDetail(channel.id)
    } finally {
      busy = false
    }
  }

  async function revoke(g: GuestInfo) {
    await api(`/api/guests/${g.id}`, { method: 'DELETE' })
    await store.loadDetail(channel.id)
  }

  async function copy() {
    await navigator.clipboard.writeText(link)
    store.toast('Link copied')
  }

  function status(g: GuestInfo) {
    if (g.revoked_at) return 'Access revoked'
    if (new Date(g.expires_at) < new Date()) return 'Link expired'
    return `${g.joined ? 'Joined' : 'Not opened yet'}, link valid until ${when(g.expires_at)}`
  }
</script>

<dialog bind:this={dlg} onclose={onclose} aria-labelledby="invTitle">
  <div class="dlg">
    <h2 id="invTitle">Invite to {channel.name}</h2>
    <p>Guests open a personal link in the browser and need no account. They only see this channel, never the backroom or any agent.</p>
    {#if link}
      <label class="field" for="link">Personal link. Send it to the guest yourself.</label>
      <div class="copy"><input id="link" readonly value={link} onfocus={(e) => (e.currentTarget as HTMLInputElement).select()} /><button class="btn" onclick={copy}>Copy</button></div>
      <div class="row"><button class="btn" onclick={() => (link = '')}>Invite someone else</button><button class="btn primary" onclick={() => dlg?.close()}>Done</button></div>
    {:else}
      <form class="dlg" style="padding:0" onsubmit={create}>
        <label class="field">Name (optional, the guest can type it)<input bind:value={name} maxlength="120" /></label>
        <label class="field">Company<input bind:value={company} maxlength="200" /></label>
        <label class="field">Link valid for days<input type="number" min="1" max="365" bind:value={days} /></label>
        <div class="row"><button type="button" class="btn" onclick={() => dlg?.close()}>Cancel</button><button class="btn primary" disabled={busy}>Create link</button></div>
      </form>
    {/if}
    {#if guests.length}
      <h3 style="margin:6px 0 0;font-size:14px">Guests</h3>
      <ul class="guest-list">
        {#each guests as g (g.id)}
          <li>
            <span class="grow">{g.name ?? 'Invited guest'}{g.company ? `, ${g.company}` : ''}<small>{status(g)}</small></span>
            {#if !g.revoked_at}<button class="btn small danger" onclick={() => revoke(g)}>Revoke</button>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</dialog>
