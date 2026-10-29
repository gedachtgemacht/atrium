<script lang="ts">
  // The guest app. It only knows the guest API under /g/api and has no code for anything internal.
  import { onMount, tick } from 'svelte'
  import { ApiError, makeApi, socketUrl } from '../lib/api'
  import Avatar from '../lib/Avatar.svelte'
  import { dayLabel, size, time } from '../lib/format'
  import { LANGS, pickLanguage, setLanguage, t } from '../lib/i18n.svelte'
  import { icons } from '../lib/icons'
  import './i18n'

  type Author = { kind: 'guest' | 'staff'; id: string; name: string; initials: string }
  type File = { id: string; filename: string; mime: string; size: number; url: string }
  type Msg = { id: string; author: Author; body: string; created_at: string; edited_at: string | null; attachments: File[] }
  type Chan = { company_name: string; partner_name: string; server_location: string; language: string; members: Author[] }
  type Me = { id: string; name: string; company: string; preview: boolean; email: string | null; notify: boolean; locale: string }

  const hash = new URLSearchParams(location.hash.slice(1))
  const previewToken = hash.get('preview')
  const loginToken = hash.get('login')
  const pathToken = location.pathname.match(/^\/g\/([A-Za-z0-9_-]{20,})/)?.[1] ?? null
  const api = makeApi((): Record<string, string> => (previewToken ? { Authorization: `Preview ${previewToken}` } : {}))

  let phase = $state<'loading' | 'name' | 'in' | 'gone'>('loading')
  let company = $state('')
  let name = $state(hash.get('name') ?? '')
  let joinEmail = $state('')
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
  let editing = $state<string | null>(null)
  let editText = $state('')
  let confirmDelete = $state<string | null>(null)
  let settingsDlg: HTMLDialogElement | undefined = $state()
  let prefEmail = $state('')
  let prefNotify = $state(false)
  let prefLocale = $state('')
  let prefMsg = $state('')

  const org = $derived(chan?.company_name ?? company)

  setLanguage(pickLanguage(navigator.language))

  function applyLanguage() {
    setLanguage(pickLanguage(me?.locale, navigator.language, chan?.language))
  }

  onMount(async () => {
    // Coming from a notification email: the link carries a fresh sign in token.
    if (loginToken) {
      try {
        me = await api<Me>('/g/api/resume', { body: { token: loginToken } })
        history.replaceState(null, '', location.pathname)
        return enter()
      } catch {}
    }
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
      const info = await api<{ company_name: string; needs_name: boolean; language: string }>('/g/api/join-info', { body: { token: pathToken } })
      company = info.company_name
      setLanguage(pickLanguage(navigator.language, info.language))
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
      me = await api<Me>('/g/api/session', { body: { token: pathToken, name, email: joinEmail || null } })
      if (location.hash) history.replaceState(null, '', location.pathname)
      await enter()
    } catch (err) {
      error = err instanceof ApiError ? err.message : t('g.failed')
      if (err instanceof ApiError && err.status === 401) phase = 'gone'
    }
  }

  async function enter() {
    ;[chan, messages] = await Promise.all([api<Chan>('/g/api/channel'), api<Msg[]>('/g/api/messages')])
    applyLanguage()
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
      } else if (e.type === 'message.updated') {
        const i = messages.findIndex((m) => m.id === e.message.id)
        if (i >= 0) messages[i] = e.message
      } else if (e.type === 'message.deleted') {
        messages = messages.filter((m) => m.id !== e.message_id)
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
    if (a.kind === 'staff') return t('g.tag_staff', { org })
    return a.id === me?.id ? t('g.tag_you') : t('g.tag_guest')
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

  async function saveEdit(m: Msg, e: SubmitEvent) {
    e.preventDefault()
    try {
      const updated = await api<Msg>(`/g/api/messages/${m.id}`, { method: 'PATCH', body: { body: editText } })
      const i = messages.findIndex((x) => x.id === m.id)
      if (i >= 0) messages[i] = updated
      editing = null
    } catch (err) {
      error = (err as Error).message
    }
  }

  async function remove(m: Msg) {
    if (confirmDelete !== m.id) {
      confirmDelete = m.id
      setTimeout(() => confirmDelete === m.id && (confirmDelete = null), 4000)
      return
    }
    confirmDelete = null
    await api(`/g/api/messages/${m.id}`, { method: 'DELETE' })
    messages = messages.filter((x) => x.id !== m.id)
  }

  function openSettings() {
    prefEmail = me?.email ?? ''
    prefNotify = me?.notify ?? false
    prefLocale = me?.locale ?? ''
    prefMsg = ''
    settingsDlg?.showModal()
  }

  async function saveSettings(e: SubmitEvent) {
    e.preventDefault()
    prefMsg = ''
    try {
      me = await api<Me>('/g/api/me', { method: 'PATCH', body: { email: prefEmail, notify: prefNotify, locale: prefLocale } })
      prefNotify = me.notify
      applyLanguage()
      prefMsg = t('g.saved')
    } catch (err) {
      prefMsg = err instanceof ApiError ? err.message : t('g.failed')
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
      <p>{t('g.invited', { org: company })}</p>
      <label class="field">{t('g.your_name')}<input bind:value={name} required minlength="2" maxlength="120" autocomplete="name" /></label>
      <label class="field">{t('g.email_opt')}<input type="email" bind:value={joinEmail} maxlength="320" autocomplete="email" /></label>
      <p style="font-size:12.5px">{t('g.email_hint', { org: company })}</p>
      {#if error}<p class="error" role="alert">{error}</p>{/if}
      <button class="btn primary">{t('g.join')}</button>
      <p style="font-size:12.5px">{t('g.join_notice', { org: company })}</p>
    </form>
  </main>
{:else if phase === 'gone'}
  <main class="center">
    <div class="card">
      <h1>{t('g.gone_title')}</h1>
      <p>{t('g.gone')}</p>
    </div>
  </main>
{:else if phase === 'in' && chan && me}
  <div class="guest-app" class:preview-mode={me.preview}>
    <header class="top">
      <div class="guest-brand">{chan.company_name} <small>{t('g.brand_sub')}</small></div>
      {#if !me.preview}<button class="btn small" style="margin-left:auto" onclick={openSettings}>{t('g.settings')}</button>{/if}
    </header>
    <main class="channel">
      <div class="chan-head">
        <div>
          <h1>{chan.company_name}</h1>
          <p class="chan-sub">{t('g.sub', { org })}</p>
          <div class="members">
            <div class="stack" aria-label={t('channel.members')}>
              {#each chan.members as m (m.id)}
                <Avatar kind={m.kind === 'guest' ? 'guest' : 'user'} size="s" initials={m.initials} title={m.name} />
              {/each}
            </div>
            <span class="rule-chip">{@html icons.person()} {t('channel.only_people')}</span>
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
                {#if m.edited_at}<span class="edited">{t('msg.edited')}</span>{/if}
                {#if m.author.id === me.id && !me.preview && editing !== m.id}
                  <span class="msg-tools">
                    <button onclick={() => { editing = m.id; editText = m.body; confirmDelete = null }}>{t('msg.edit')}</button>
                    <button class:danger={confirmDelete === m.id} onclick={() => remove(m)}>{confirmDelete === m.id ? t('msg.really_delete') : t('msg.delete')}</button>
                  </span>
                {/if}
              </div>
              {#if editing === m.id}
                <form class="edit-box" onsubmit={(e) => saveEdit(m, e)}>
                  <label class="sr" for="edit-{m.id}">{t('msg.edit_label')}</label>
                  <textarea id="edit-{m.id}" bind:value={editText}
                    onkeydown={(e) => { if (e.key === 'Escape') editing = null; if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); (e.currentTarget as HTMLTextAreaElement).form?.requestSubmit() } }}></textarea>
                  <div class="row"><button class="btn small primary">{t('msg.save')}</button><button type="button" class="btn small" onclick={() => (editing = null)}>{t('msg.cancel')}</button></div>
                </form>
              {:else if m.body}<p class="body">{m.body}</p>{/if}
              {#each m.attachments as f (f.id)}
                <a class="doc" href={previewToken ? undefined : f.url} target="_blank" rel="noopener">{@html icons.doc()}<div><strong>{f.filename}</strong><small>{size(f.size)}</small></div></a>
              {/each}
            </div>
          </div>
        {:else}
          <p class="empty-feed">{t('g.empty')}</p>
        {/each}
      </div>
      <form class="composer" onsubmit={send}>
        {#each uploads as f, i (f.id)}
          <div class="attach plain">{@html icons.doc()}<span class="grow"><strong>{f.filename}</strong><small>{size(f.size)}</small></span>
            <button type="button" class="x" aria-label={t('composer.remove_file')} onclick={() => uploads.splice(i, 1)}>{@html icons.x()}</button></div>
        {/each}
        <div class="box">
          <label class="sr" for="msg">{t('composer.message')}</label>
          <textarea id="msg" rows="1" bind:this={input} bind:value={text} oninput={grow} disabled={me.preview}
            placeholder={me.preview ? t('g.preview_ro') : t('g.to', { org })}
            onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send() } }}></textarea>
          <input type="file" hidden multiple bind:this={fileInput} onchange={pick} />
          <button type="button" class="clip" aria-label={t('composer.attach')} disabled={me.preview} onclick={() => fileInput?.click()}>{@html icons.clip()}</button>
          <button class="btn primary" type="submit" disabled={sending || me.preview}>{t('composer.send')}</button>
        </div>
        {#if error}<p class="composer-error" role="alert">{error}</p>{/if}
        <p class="composer-hint">{t('g.notice', { org, where: chan.server_location ? t('g.where', { place: chan.server_location }) : '' })}</p>
      </form>
    </main>
  </div>

  <dialog bind:this={settingsDlg} aria-labelledby="gsTitle">
    <form class="dlg" onsubmit={saveSettings}>
      <h2 id="gsTitle">{t('g.settings_title')}</h2>
      <label class="field">{t('g.email')}<input type="email" bind:value={prefEmail} maxlength="320" autocomplete="email" /></label>
      <label class="check"><input type="checkbox" bind:checked={prefNotify} disabled={!prefEmail} /> {t('g.notify', { org })}</label>
      <p>{t('g.email_hint', { org })}</p>
      <label class="field">{t('g.language')}
        <select bind:value={prefLocale}>
          <option value="">{t('g.lang_auto')}</option>
          {#each LANGS as l}<option value={l}>{l === 'de' ? 'Deutsch' : 'English'}</option>{/each}
        </select>
      </label>
      {#if prefMsg}<p role="status">{prefMsg}</p>{/if}
      <div class="row">
        <button type="button" class="btn" onclick={() => settingsDlg?.close()}>{t('common.done')}</button>
        <button class="btn primary">{t('msg.save')}</button>
      </div>
    </form>
  </dialog>
{/if}
