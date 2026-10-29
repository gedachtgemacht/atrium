<script lang="ts">
  import { list, t } from '../lib/i18n.svelte'
  import { api } from '../lib/api'
  import Avatar from '../lib/Avatar.svelte'
  import { firstName, parts, size, time } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { Message } from '../lib/types'
  import { store } from './store.svelte'
  import WorkCard from './WorkCard.svelte'

  let { message, where }: { message: Message; where: 'shared' | 'internal' | 'backroom' } = $props()
  let el: HTMLElement | undefined = $state()
  let pulling = $state(false)
  let note = $state('')
  let busy = $state(false)
  let editing = $state(false)
  let editText = $state('')
  let confirmDelete = $state(false)

  const me = $derived(store.me?.id)
  const a = $derived(message.author)
  const mine = $derived(a.kind === 'user' && a.id === me)
  const tag = $derived(
    a.kind === 'agent' ? t('msg.agent')
      : a.kind === 'guest' ? (a.label ? t('msg.guest_from', { company: a.label }) : t('msg.guest'))
      : mine ? (a.label ? t('msg.tag_you', { label: a.label }) : t('common.You'))
      : a.label,
  )
  const canEdit = $derived(mine && !message.pulled_from)
  const canDelete = $derived(canEdit || (a.kind === 'agent' && where !== 'shared'))
  const marks = $derived(rememberedAs(message.memory_marks.map((m) => m.kind)))

  function rememberedAs(kinds: string[]) {
    const uniq = [...new Set(kinds)].map((k) => t(`mem.word.${k}`))
    return uniq.length ? t('msg.remembered', { kinds: list(uniq) }) : ''
  }

  function by(name: string, id: string | null) {
    return id === me ? t('common.you') : firstName(name)
  }

  async function pull(e: SubmitEvent) {
    e.preventDefault()
    busy = true
    try {
      const copy = await api<Message>(`/api/messages/${message.id}/pull`, { body: { note } })
      pulling = false
      note = ''
      store.backroomTab = 'work'
      store.backroomOpen = true
      setTimeout(() => store.flash(copy.id), 250)
    } catch (err) {
      store.toast(t('msg.pull_failed'))
    } finally {
      busy = false
    }
  }

  function startEdit() {
    editText = message.body
    editing = true
    confirmDelete = false
  }

  async function saveEdit(e: SubmitEvent) {
    e.preventDefault()
    try {
      store.upsertMessage(await api<Message>(`/api/messages/${message.id}`, { method: 'PATCH', body: { body: editText } }))
      editing = false
    } catch (err) {
      store.toast((err as Error).message)
    }
  }

  async function remove() {
    if (!confirmDelete) {
      confirmDelete = true
      setTimeout(() => (confirmDelete = false), 4000)
      return
    }
    try {
      await api(`/api/messages/${message.id}`, { method: 'DELETE' })
    } catch (err) {
      store.toast((err as Error).message)
    }
  }

  $effect(() => {
    if (store.flashId === message.id && el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
</script>

{#if where === 'backroom' && message.pulled_from}
  <div class="pull-card" class:flash={store.flashId === message.id} bind:this={el} id="m-{message.id}">
    <div class="pull-meta">{@html icons.arrow()}
      {message.pulled_from.by_id === me ? t('msg.pulled_card_me', { time: time(message.pulled_from.at) }) : t('msg.pulled_card', { who: firstName(message.pulled_from.by_name), time: time(message.pulled_from.at) })}
    </div>
    <blockquote>
      <Avatar kind={a.kind} size="s" initials={a.initials} tone={a.tone} />
      <div><strong>{a.name}</strong><p>{message.body}</p>
        {#each message.attachments as f (f.id)}
          <a class="doc" href={f.url} target="_blank" rel="noopener">{@html icons.doc()}<div><strong>{f.filename}</strong><small>{size(f.size)}</small></div></a>
        {/each}
      </div>
    </blockquote>
  </div>
  {#if marks}<div class="captured">{@html icons.mark()}{marks}</div>{/if}
{:else}
  <div class="msg" class:flash={store.flashId === message.id} bind:this={el} id="m-{message.id}">
    <Avatar kind={a.kind} initials={a.initials} tone={a.tone} />
    <div>
      <div class="msg-head">
        <span class="name">{a.name}</span>
        {#if tag}<span class="tag" class:guest={a.kind === 'guest'} class:agent={a.kind === 'agent'}>{tag}</span>{/if}
        <span class="time">{time(message.created_at)}</span>
        {#if message.edited_at}<span class="edited">{t('msg.edited')}</span>{/if}
        {#if (canEdit || canDelete) && !editing}
          <span class="msg-tools">
            {#if canEdit}<button onclick={startEdit}>{t('msg.edit')}</button>{/if}
            {#if canDelete}<button class:danger={confirmDelete} onclick={remove}>{confirmDelete ? t('msg.really_delete') : t('msg.delete')}</button>{/if}
          </span>
        {/if}
      </div>
      {#if editing}
        <form class="edit-box" onsubmit={saveEdit}>
          <label class="sr" for="edit-{message.id}">{t('msg.edit_label')}</label>
          <!-- svelte-ignore a11y_autofocus -->
          <textarea id="edit-{message.id}" bind:value={editText} autofocus
            onkeydown={(e) => { if (e.key === 'Escape') editing = false; if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); (e.currentTarget as HTMLTextAreaElement).form?.requestSubmit() } }}></textarea>
          <div class="row"><button class="btn small primary">{t('msg.save')}</button><button type="button" class="btn small" onclick={() => (editing = false)}>{t('msg.cancel')}</button></div>
          {#if where === 'shared'}<p class="composer-hint" style="margin:0">{t('msg.edit_shared_hint', { partner: store.current?.partner_name || t('msg.customer') })}</p>{/if}
        </form>
      {:else if message.body}
        <p class="body">{#each parts(message.body) as p}{#if p.mention}<span class="mention">{p.text}</span>{:else}{p.text}{/if}{/each}</p>
      {/if}
      {#each message.attachments as f (f.id)}
        <a class="doc" href={f.url} target="_blank" rel="noopener">{@html icons.doc()}<div><strong>{f.filename}</strong><small>{f.summary || size(f.size)}</small></div></a>
      {/each}
      {#each message.work_results as w (w.id)}
        <WorkCard work={w} agent={a.name} />
      {/each}
      {#if where === 'shared' && a.kind === 'guest'}
        {#if message.pulled}
          <div class="pulled">{@html icons.lock()}{message.pulled.by_id === me ? t('msg.pulled_by_me', { time: time(message.pulled.at) }) : t('msg.pulled_by', { who: by(message.pulled.by_name, message.pulled.by_id), time: time(message.pulled.at) })}</div>
        {:else if pulling}
          <form class="pull-form" onsubmit={pull}>
            <label class="sr" for="note-{message.id}">{t('msg.pull_note_label')}</label>
            <!-- svelte-ignore a11y_autofocus -->
            <input id="note-{message.id}" placeholder={t('msg.pull_note')} bind:value={note} autofocus />
            <button class="btn small primary" disabled={busy}>{t('msg.pull_in')}</button>
            <button class="btn small" type="button" onclick={() => (pulling = false)}>{t('msg.cancel')}</button>
          </form>
        {:else}
          <button class="pull-btn" onclick={() => (pulling = true)}>{@html icons.arrow()}{t('msg.pull')}</button>
        {/if}
      {/if}
    </div>
  </div>
  {#if marks && where !== 'shared'}<div class="captured">{@html icons.mark()}{marks}</div>{/if}
{/if}
