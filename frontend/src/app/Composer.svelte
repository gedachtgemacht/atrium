<script lang="ts">
  import { list, t } from '../lib/i18n.svelte'
  import { api } from '../lib/api'
  import { size } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { Attachment, Channel, Draft } from '../lib/types'
  import { store } from './store.svelte'

  let {
    channel,
    placeholder,
    hint,
    backroom = false,
  }: { channel: Channel; placeholder: string; hint: string; backroom?: boolean } = $props()

  let text = $state('')
  let uploads = $state<Attachment[]>([])
  let error = $state('')
  let sending = $state(false)
  let flashing = $state(false)
  let input: HTMLTextAreaElement | undefined = $state()
  let fileInput: HTMLInputElement | undefined = $state()
  const seen = new Set<string>()

  const drafts = $derived(backroom ? [] : store.drafts.filter((d) => d.channel_id === channel.id))

  // A new agent draft lands in this person's composer: text in, files attached, short highlight.
  $effect(() => {
    for (const d of drafts) {
      if (seen.has(d.id)) continue
      seen.add(d.id)
      if (d.body) text = text.trim() ? `${text.trim()}\n\n${d.body}` : d.body
      highlight()
    }
  })

  $effect(() => {
    if (store.composerFlash && !backroom) highlight()
  })

  function highlight() {
    flashing = false
    queueMicrotask(() => {
      flashing = true
      grow()
      input?.focus({ preventScroll: true })
      setTimeout(() => (flashing = false), 900)
    })
  }

  function grow() {
    if (!input) return
    input.style.height = 'auto'
    input.style.height = Math.min(input.scrollHeight, 150) + 'px'
  }

  async function removeDraftFile(d: Draft, f: Attachment) {
    await api(`/api/drafts/${d.id}/attachments/${f.id}`, { method: 'DELETE' })
    await store.loadDrafts()
  }

  async function discard(d: Draft) {
    if (d.body && text.includes(d.body)) text = text.replace(d.body, '').trim()
    await api(`/api/drafts/${d.id}`, { method: 'DELETE' })
    await store.loadDrafts()
  }

  async function pick() {
    const files = fileInput?.files
    if (!files?.length) return
    error = ''
    for (const f of files) {
      const form = new FormData()
      form.append('file', f)
      try {
        uploads.push(await api<Attachment>('/api/files', { form }))
      } catch (e) {
        error = (e as Error).message
      }
    }
    fileInput!.value = ''
  }

  async function send(e?: SubmitEvent) {
    e?.preventDefault()
    const body = text.trim()
    if (!body && !uploads.length && !drafts.some((d) => d.attachments.length)) return
    sending = true
    error = ''
    try {
      await api(`/api/channels/${channel.id}/messages`, {
        body: { body, attachment_ids: uploads.map((u) => u.id), draft_ids: drafts.map((d) => d.id) },
      })
      text = ''
      uploads = []
      grow()
      if (drafts.length) store.loadDrafts()
    } catch (err) {
      error = (err as Error).message
    } finally {
      sending = false
    }
  }

  function keydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault()
      send()
    }
  }
</script>

<form class={backroom ? 'back-composer' : 'composer'} onsubmit={send}>
  {#each drafts as d (d.id)}
    {#each d.attachments as f (f.id)}
      <div class="attach">
        {@html icons.doc()}
        <span class="grow"><strong>{f.filename}</strong><small>{f.summary || size(f.size)}</small></span>
        <button type="button" class="x" aria-label={t('composer.remove_attachment')} onclick={() => removeDraftFile(d, f)}>{@html icons.x()}</button>
      </div>
    {/each}
  {/each}
  {#each uploads as f, i (f.id)}
    <div class="attach plain">
      {@html icons.doc()}
      <span class="grow"><strong>{f.filename}</strong><small>{size(f.size)}</small></span>
      <button type="button" class="x" aria-label={t('composer.remove_file')} onclick={() => uploads.splice(i, 1)}>{@html icons.x()}</button>
    </div>
  {/each}
  <div class="box" class:flash={flashing}>
    <label class="sr" for="in-{channel.id}">{backroom ? t('composer.backroom_label') : t('composer.message')}</label>
    <textarea id="in-{channel.id}" rows="1" {placeholder} bind:value={text} bind:this={input} oninput={grow} onkeydown={keydown}></textarea>
    <input type="file" hidden multiple bind:this={fileInput} onchange={pick} />
    <button type="button" class="clip" aria-label={t('composer.attach')} onclick={() => fileInput?.click()}>{@html icons.clip()}</button>
    <button class="btn primary" type="submit" disabled={sending}>{t('composer.send')}</button>
  </div>
  {#if error}<p class="composer-error" role="alert">{error}</p>{/if}
  <p class="composer-hint">
    {hint}
    {#each drafts as d (d.id)}
      <span> {t('composer.draft_from', { agent: d.agent_name || 'Agent' })} <button type="button" class="link-btn" onclick={() => discard(d)}>{t('composer.discard')}</button></span>
    {/each}
  </p>
</form>
