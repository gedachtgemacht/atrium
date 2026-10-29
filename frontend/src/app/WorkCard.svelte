<script lang="ts">
  import { list, t } from '../lib/i18n.svelte'
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
  const who = $derived(firstName(work.staged_by_name))

  const stateLabel = $derived(
    work.status === 'sent' ? t('work.sent', { time: work.sent_at ? time(work.sent_at) : '' }) : work.status === 'with_user' ? (mineStaged ? t('work.with_me') : t('work.with', { name: who })) : work.kind === 'quote' ? t('work.draft_internal') : t('work.internal'),
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
      <thead><tr><th>{t('work.route')}</th><th class="num">{t('work.loads')}</th><th class="num">{t('work.price')}</th></tr></thead>
      <tbody>
        {#each lines as l, i}
          <tr>
            <td>{l.origin} → {l.destination}{#if l.new}<span class="new">{t('work.new')}</span>{/if}</td>
            <td class="num">{l.loads}</td>
            <td class="num rate">
              {#if editing}<input type="number" min="0" step="1" aria-label={t('work.price_for', { place: l.destination })} bind:value={rates[i]} />{:else}{eur(l.rate)}{/if}
            </td>
          </tr>
        {/each}
      </tbody>
      <tfoot><tr><td>{t('work.per_month')}</td><td class="num">{loads}</td><td class="num">{eur(total)}</td></tr></tfoot>
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
    <div class="sources" aria-label={t('work.sources')}>{#each work.sources as s}<span>{s}</span>{/each}</div>
  {/if}
  {#if why && work.data.reasoning?.length}
    <div class="reasoning" id="why-{work.id}">{#each work.data.reasoning as r}<p>{r}</p>{/each}</div>
  {/if}
  {#if work.permission}
    <div class="perm">{@html icons.lock(14)}<span>{work.permission}</span></div>
  {/if}

  {#if work.status === 'internal'}
    <div class="actions">
      <button class="btn primary" onclick={stage} disabled={busy}>{work.kind === 'quote' ? t('work.stage_quote') : t('work.stage_reply')}</button>
      {#if work.kind === 'quote'}<button class="btn" onclick={toggleEdit} disabled={busy}>{editing ? t('common.done') : t('work.edit_prices')}</button>{/if}
      {#if work.data.reasoning?.length}
        <button class="btn" aria-expanded={why} aria-controls="why-{work.id}" onclick={() => (why = !why)}>{why ? t('work.why_hide') : t('work.why')}</button>
      {/if}
    </div>
  {:else if work.status === 'with_user'}
    <div class="sent-line">{@html icons.check()}<div>
      {mineStaged ? t('work.mine_staged') : t('work.other_staged', { name: who })}<br>
      <span>{mineStaged ? t('work.mine_send') : t('work.other_send', { name: who })}</span></div></div>
  {:else}
    <div class="sent-line done">{@html icons.check()}<div>
      {mineStaged ? t('work.sent_by_me', { time: work.sent_at ? `, ${time(work.sent_at)}` : '' }) : t('work.sent_by', { name: who, time: work.sent_at ? `, ${time(work.sent_at)}` : '' })}<br>
      <span>{mineStaged ? t('work.sent_as_mine', { agent }) : t('work.sent_as_other', { name: who, agent })}</span></div></div>
  {/if}
</div>
