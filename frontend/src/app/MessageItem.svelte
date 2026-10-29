<script lang="ts">
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
  const tag = $derived(a.kind === 'agent' ? 'Agent' : mine ? (a.label ? `${a.label}, you` : 'You') : a.label)
  const canEdit = $derived(mine && !message.pulled_from)
  const canDelete = $derived(canEdit || (a.kind === 'agent' && where !== 'shared'))
  const marks = $derived(rememberedAs(message.memory_marks.map((m) => m.kind)))

  function rememberedAs(kinds: string[]) {
    const words = { decided: 'decision', open: 'open question', committed: 'promise' } as Record<string, string>
    const uniq = [...new Set(kinds)].map((k) => words[k] ?? k)
    if (!uniq.length) return ''
    return 'Remembered as ' + (uniq.length === 1 ? uniq[0] : `${uniq.slice(0, -1).join(', ')} and ${uniq[uniq.length - 1]}`)
  }

  function by(name: string, id: string | null) {
    return id === me ? 'you' : firstName(name)
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
      store.toast('Pulling didn\'t work. Try again.')
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
      {message.pulled_from.by_id === me ? 'You' : firstName(message.pulled_from.by_name)} pulled this in from the customer channel, {time(message.pulled_from.at)}
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
        {#if message.edited_at}<span class="edited">edited</span>{/if}
        {#if (canEdit || canDelete) && !editing}
          <span class="msg-tools">
            {#if canEdit}<button onclick={startEdit}>Edit</button>{/if}
            {#if canDelete}<button class:danger={confirmDelete} onclick={remove}>{confirmDelete ? 'Really delete?' : 'Delete'}</button>{/if}
          </span>
        {/if}
      </div>
      {#if editing}
        <form class="edit-box" onsubmit={saveEdit}>
          <label class="sr" for="edit-{message.id}">Edit message</label>
          <!-- svelte-ignore a11y_autofocus -->
          <textarea id="edit-{message.id}" bind:value={editText} autofocus
            onkeydown={(e) => { if (e.key === 'Escape') editing = false; if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); (e.currentTarget as HTMLTextAreaElement).form?.requestSubmit() } }}></textarea>
          <div class="row"><button class="btn small primary">Save</button><button type="button" class="btn small" onclick={() => (editing = false)}>Cancel</button></div>
          {#if where === 'shared'}<p class="composer-hint" style="margin:0">{store.current?.partner_name || 'The customer'} sees the new text, marked as edited.</p>{/if}
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
          <div class="pulled">{@html icons.lock()}Pulled into the backroom by {by(message.pulled.by_name, message.pulled.by_id)}, {time(message.pulled.at)}</div>
        {:else if pulling}
          <form class="pull-form" onsubmit={pull}>
            <label class="sr" for="note-{message.id}">Note for the backroom</label>
            <!-- svelte-ignore a11y_autofocus -->
            <input id="note-{message.id}" placeholder="Note for the backroom, like @QuoteAgent (optional)" bind:value={note} autofocus />
            <button class="btn small primary" disabled={busy}>Pull in</button>
            <button class="btn small" type="button" onclick={() => (pulling = false)}>Cancel</button>
          </form>
        {:else}
          <button class="pull-btn" onclick={() => (pulling = true)}>{@html icons.arrow()}Pull into backroom</button>
        {/if}
      {/if}
    </div>
  </div>
  {#if marks && where !== 'shared'}<div class="captured">{@html icons.mark()}{marks}</div>{/if}
{/if}
