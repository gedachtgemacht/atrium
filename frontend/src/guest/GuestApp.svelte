<script lang="ts">
  // The guest app. It only knows the guest API under /g/api and has no code for anything internal.
  import { onMount, tick } from 'svelte'
  import { ApiError, makeApi, socketUrl } from '../lib/api'
  import Avatar from '../lib/Avatar.svelte'
  import { dayLabel, size, time } from '../lib/format'
  import { icons } from '../lib/icons'

  type Author = { kind: 'guest' | 'staff'; id: string; name: string; initials: string }
  type File = { id: string; filename: string; mime: string; size: number; url: string }
  type Msg = { id: string; author: Author; body: string; created_at: string; attachments: File[] }
  type Chan = { company_name: string; partner_name: string; notice: string; members: Author[] }
  type Me = { id: string; name: string; company: string; preview: boolean }

  const hash = new URLSearchParams(location.hash.slice(1))
  const previewToken = hash.get('preview')
  const pathToken = location.pathname.match(/^\/g\/([A-Za-z0-9_-]{20,})/)?.[1] ?? null
  const api = makeApi((): Record<string, string> => (previewToken ? { Authorization: `Preview ${previewToken}` } : {}))

  let phase = $state<'loading' | 'name' | 'in' | 'gone'>('loading')
  let company = $state('')
  let name = $state(hash.get('name') ?? '')
  let error = $state('')
  let me = $state<Me | null>(null)
  let chan = $state<Chan | null>(null)
  let messages = $state<Msg[]>([])
  let text = $state('')
  let uploads = $state<File[]>([])
  let sending = $state(false)
  let feed: HTMLElement | undefined = $state()
  let input: HTMLTextAreaElement | undefined = $state()
  let fileInput: HTMLInputElement | undefined = $state()

  onMount(async () => {
    try {
      me = await api<Me>('/g/api/me')
      return enter()
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401 || !pathToken) {
        phase = 'gone'
        return
      }
    }
    try {
      const info = await api<{ company_name: string; needs_name: boolean }>('/g/api/join-info', { body: { token: pathToken } })
      company = info.company_name
      if (info.needs_name) phase = 'name'
      else await join()
    } catch {
      phase = 'gone'
    }
  })

  async function join(e?: SubmitEvent) {
    e?.preventDefault()
    error = ''
    try {
      me = await api<Me>('/g/api/session', { body: { token: pathToken, name } })
      if (location.hash) history.replaceState(null, '', location.pathname)
      await enter()
    } catch (err) {
      error = err instanceof ApiError ? err.message : 'That didn\'t work.'
      if (err instanceof ApiError && err.status === 401) phase = 'gone'
    }
  }

  async function enter() {
    ;[chan, messages] = await Promise.all([api<Chan>('/g/api/channel'), api<Msg[]>('/g/api/messages')])
    document.title = chan.company_name
    phase = 'in'
    await tick()
    feed?.scrollTo({ top: feed.scrollHeight })
    connect()
  }

  function connect() {
    const ws = new WebSocket(socketUrl('/g/ws' + (previewToken ? `?preview=${encodeURIComponent(previewToken)}` : '')))
    ws.onmessage = async (ev) => {
      const e = JSON.parse(ev.data)
      if (e.type === 'message.created' && !messages.some((m) => m.id === e.message.id)) {
        messages.push(e.message)
        await tick()
        feed?.scrollTo({ top: feed.scrollHeight, behavior: 'smooth' })
      } else if (e.type === 'members.updated' && chan) {
        chan.members = e.members
      }
    }
    ws.onclose = (ev) => {
      if (ev.code === 4401) phase = 'gone'
      else setTimeout(connect, 3000)
    }
  }

  function tag(a: Author) {
    if (a.kind === 'staff') return chan?.company_name ?? ''
    return a.id === me?.id ? 'You' : 'Guest'
  }

  function grow() {
    if (!input) return
    input.style.height = 'auto'
    input.style.height = Math.min(input.scrollHeight, 150) + 'px'
  }

  async function pick() {
    for (const f of fileInput?.files ?? []) {
      const form = new FormData()
      form.append('file', f)
      try {
        uploads.push(await api<File>('/g/api/files', { form }))
      } catch (e) {
        error = (e as Error).message
      }
    }
    if (fileInput) fileInput.value = ''
  }

  async function send(e?: SubmitEvent) {
    e?.preventDefault()
    if (me?.preview || (!text.trim() && !uploads.length)) return
    sending = true
    error = ''
    try {
      const m = await api<Msg>('/g/api/messages', { body: { body: text, attachment_ids: uploads.map((u) => u.id) } })
      if (!messages.some((x) => x.id === m.id)) messages.push(m)
      text = ''
      uploads = []
      grow()
    } catch (err) {
      error = (err as Error).message
    } finally {
      sending = false
    }
  }

  function newDay(i: number) {
    return i === 0 || new Date(messages[i].created_at).toDateString() !== new Date(messages[i - 1].created_at).toDateString()
  }
</script>

{#if phase === 'name'}
  <main class="center">
    <form class="card" onsubmit={join}>
      <h1>{company}</h1>
      <p>You've been invited to a shared channel with {company}. You don't need an account. What's your name?</p>
      <label class="field">Your name<input bind:value={name} required minlength="2" maxlength="120" autocomplete="name" /></label>
      {#if error}<p class="error" role="alert">{error}</p>{/if}
      <button class="btn primary">Join</button>
      <p style="font-size:12.5px">Only people from {company} write in this channel. Messages are stored on their server.</p>
    </form>
  </main>
{:else if phase === 'gone'}
  <main class="center">
    <div class="card">
      <h1>Link not valid</h1>
      <p>This link has expired or was withdrawn. Ask the person who sent it for a new one.</p>
    </div>
  </main>
{:else if phase === 'in' && chan && me}
  <div class="guest-app" class:preview-mode={me.preview}>
    <header class="top">
      <div class="guest-brand">{chan.company_name} <small>in your browser, no account</small></div>
    </header>
    <main class="channel">
      <div class="chan-head">
        <div>
          <h1>{chan.company_name}</h1>
          <p class="chan-sub">Your channel with {chan.company_name}. You're here by link and don't need an account.</p>
          <div class="members">
            <div class="stack" aria-label="Members">
              {#each chan.members as m (m.id)}
                <Avatar kind={m.kind === 'guest' ? 'guest' : 'user'} size="s" initials={m.initials} title={m.name} />
              {/each}
            </div>
            <span class="rule-chip">{@html icons.person()} Only people write here</span>
          </div>
        </div>
      </div>
      <div class="feed" bind:this={feed} aria-live="polite">
        {#each messages as m, i (m.id)}
          {#if newDay(i)}<div class="day">{dayLabel(m.created_at)}</div>{/if}
          <div class="msg">
            <Avatar kind={m.author.kind === 'guest' ? 'guest' : 'user'} initials={m.author.initials} />
            <div>
              <div class="msg-head">
                <span class="name">{m.author.name}</span>
                <span class="tag" class:guest={m.author.kind === 'guest'}>{tag(m.author)}</span>
                <span class="time">{time(m.created_at)}</span>
              </div>
              {#if m.body}<p class="body">{m.body}</p>{/if}
              {#each m.attachments as f (f.id)}
                <a class="doc" href={previewToken ? undefined : f.url} target="_blank" rel="noopener">{@html icons.doc()}<div><strong>{f.filename}</strong><small>{size(f.size)}</small></div></a>
              {/each}
            </div>
          </div>
        {:else}
          <p class="empty-feed">No messages yet. Say hello.</p>
        {/each}
      </div>
      <form class="composer" onsubmit={send}>
        {#each uploads as f, i (f.id)}
          <div class="attach plain">{@html icons.doc()}<span class="grow"><strong>{f.filename}</strong><small>{size(f.size)}</small></span>
            <button type="button" class="x" aria-label="Remove file" onclick={() => uploads.splice(i, 1)}>{@html icons.x()}</button></div>
        {/each}
        <div class="box">
          <label class="sr" for="msg">Message</label>
          <textarea id="msg" rows="1" bind:this={input} bind:value={text} oninput={grow} disabled={me.preview}
            placeholder={me.preview ? 'Preview, read only' : `Message to ${chan.company_name}`}
            onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send() } }}></textarea>
          <input type="file" hidden multiple bind:this={fileInput} onchange={pick} />
          <button type="button" class="clip" aria-label="Attach a file" disabled={me.preview} onclick={() => fileInput?.click()}>{@html icons.clip()}</button>
          <button class="btn primary" type="submit" disabled={sending || me.preview}>Send</button>
        </div>
        {#if error}<p class="composer-error" role="alert">{error}</p>{/if}
        <p class="composer-hint">{chan.notice}</p>
      </form>
    </main>
  </div>
{/if}
