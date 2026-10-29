<script lang="ts">
  import { api } from '../lib/api'
  import { eur, firstName, time } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { WorkResult } from '../lib/types'
  import { store } from './store.svelte'

  let { work, agent }: { work: WorkResult; agent: string } = $props()
  let editing = $state(false)
  let rates = $state<number[]>([])
  let why = $state(false)
  let busy = $state(false)

  const me = $derived(store.me?.id)
  const lines = $derived((work.data.lines ?? []) as { origin: string; destination: string; loads: number; rate: number; new: boolean }[])
  const total = $derived(editing ? lines.reduce((s, l, i) => s + l.loads * (Number(rates[i]) || 0), 0) : work.data.total_per_month)
  const loads = $derived(lines.reduce((s, l) => s + l.loads, 0))
  const mineStaged = $derived(work.staged_by_id === me)
  const who = $derived(mineStaged ? 'you' : firstName(work.staged_by_name))

  const stateLabel = $derived(
    work.status === 'sent' ? `Sent ${work.sent_at ? time(work.sent_at) : ''}` : work.status === 'with_user' ? `With ${mineStaged ? 'you' : firstName(work.staged_by_name)}` : work.kind === 'quote' ? 'Draft, internal only' : 'Internal only',
  )

  async function toggleEdit() {
    if (!editing) {
      rates = lines.map((l) => l.rate)
      editing = true
      return
    }
    busy = true
    try {
      await api(`/api/work-results/${work.id}`, { method: 'PATCH', body: { rates: rates.map((r) => Math.max(0, Math.round(Number(r) || 0))) } })
      editing = false
    } catch (e) {
      store.toast((e as Error).message)
    } finally {
      busy = false
    }
  }

  async function stage() {
    busy = true
    try {
      if (editing) await toggleEdit()
      await api(`/api/work-results/${work.id}/stage`, { method: 'POST' })
      await store.loadDrafts()
      store.backroomOpen = false
      store.composerFlash++
    } catch (e) {
      store.toast((e as Error).message)
    } finally {
      busy = false
    }
  }
</script>

<div class="work">
  <div class="work-head">
    <strong>{work.title}</strong>
    <span class="state" class:staged={work.status === 'with_user'} class:sent={work.status === 'sent'}>{stateLabel}</span>
  </div>

  {#if work.kind === 'quote'}
    <table>
      <thead><tr><th>Route</th><th class="num">Loads</th><th class="num">Price per load</th></tr></thead>
      <tbody>
        {#each lines as l, i}
          <tr>
            <td>{l.origin} → {l.destination}{#if l.new}<span class="new">new</span>{/if}</td>
            <td class="num">{l.loads}</td>
            <td class="num rate">
              {#if editing}<input type="number" min="0" step="1" aria-label="Price per load {l.destination}" bind:value={rates[i]} />{:else}{eur(l.rate)}{/if}
            </td>
          </tr>
        {/each}
      </tbody>
      <tfoot><tr><td>Per month</td><td class="num">{loads}</td><td class="num">{eur(total)}</td></tr></tfoot>
    </table>
  {:else if work.kind === 'payment_terms'}
    <dl class="calc">
      {#each work.data.rows ?? [] as r}<dt>{r.label}</dt><dd>{r.value}</dd>{/each}
    </dl>
  {/if}

  {#if work.data.note}
    <div class="note">{@html icons.info()}<span>{work.data.note}</span></div>
  {/if}
  {#if work.sources.length}
    <div class="sources" aria-label="Where the numbers come from">{#each work.sources as s}<span>{s}</span>{/each}</div>
  {/if}
  {#if why && work.data.reasoning?.length}
    <div class="reasoning" id="why-{work.id}">{#each work.data.reasoning as r}<p>{r}</p>{/each}</div>
  {/if}
  {#if work.permission}
    <div class="perm">{@html icons.lock(14)}<span>{work.permission}</span></div>
  {/if}

  {#if work.status === 'internal'}
    <div class="actions">
      <button class="btn primary" onclick={stage} disabled={busy}>{work.kind === 'quote' ? 'Move to customer channel' : 'Draft a reply in the customer channel'}</button>
      {#if work.kind === 'quote'}<button class="btn" onclick={toggleEdit} disabled={busy}>{editing ? 'Done' : 'Change prices'}</button>{/if}
      {#if work.data.reasoning?.length}
        <button class="btn" aria-expanded={why} aria-controls="why-{work.id}" onclick={() => (why = !why)}>{why ? 'Hide reasoning' : 'Reasoning'}</button>
      {/if}
    </div>
  {:else if work.status === 'with_user'}
    <div class="sent-line">{@html icons.check()}<div>
      {mineStaged ? "It's in your composer in the customer channel now." : `It's in ${who}'s composer in the customer channel.`}<br>
      <span>It only goes out when {mineStaged ? 'you press' : `${who} presses`} Send there.</span></div></div>
  {:else}
    <div class="sent-line done">{@html icons.check()}<div>
      Sent to the customer by {who}{work.sent_at ? `, ${time(work.sent_at)}` : ''}.<br>
      <span>Went out as {mineStaged ? 'your' : `${who}'s`} message, not as {agent}.</span></div></div>
  {/if}
</div>
