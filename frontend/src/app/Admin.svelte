<script lang="ts">
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { when } from '../lib/format'
  import { LANGS, setLanguage, t } from '../lib/i18n.svelte'
  import './i18n-admin'
  import RoomsEditor from './RoomsEditor.svelte'
  import { store } from './store.svelte'

  type Tab = 'audit' | 'settings' | 'people' | 'guests' | 'channels' | 'rooms'
  type AuditRow = { id: string; at: string; actor_kind: string; actor_name: string; action: string; subject_id: string | null; details: Record<string, unknown> }
  type Settings = { name: string; language: string; server_location: string; interest_rate_pct: string; retention: Record<string, number | null>; llm_provider: string | null; llm_providers: string[]; default_llm_provider: string }
  type UserRow = { id: string; email: string; name: string; role_label: string; is_admin: boolean; is_active: boolean }
  type GuestRow = { id: string; name: string | null; company: string; channel_name: string; created_at: string; expires_at: string; revoked_at: string | null; message_count: number }
  type ChannelRow = { id: string; kind: string; name: string; partner_name: string; member_ids: string[] }

  const TABS: Tab[] = ['audit', 'settings', 'people', 'guests', 'channels', 'rooms']
  const FILTERS = ['', 'message.pulled', 'draft', 'llm.call', 'guest', 'memory', 'rooms', 'settings']

  let tab = $state<Tab>('audit')
  let audit = $state<AuditRow[]>([])
  let filter = $state('')
  let settings = $state<Settings | null>(null)
  let saved = $state('')
  let users = $state<UserRow[]>([])
  let guests = $state<GuestRow[]>([])
  let channels = $state<ChannelRow[]>([])
  let newUser = $state({ email: '', name: '', password: '', role_label: '', is_admin: false })
  let error = $state('')

  async function load(which: Tab) {
    error = ''
    if (which === 'audit') audit = await api<AuditRow[]>(`/api/admin/audit?limit=200${filter ? `&action=${encodeURIComponent(filter)}` : ''}`)
    if (which === 'settings') settings = await api<Settings>('/api/admin/settings')
    if (which === 'people') users = await api<UserRow[]>('/api/admin/users')
    if (which === 'guests') guests = await api<GuestRow[]>('/api/admin/guests')
    if (which === 'channels') {
      ;[channels, users] = await Promise.all([api<ChannelRow[]>('/api/admin/channels'), api<UserRow[]>('/api/admin/users')])
    }
  }

  onMount(() => load(tab))

  function open(which: Tab) {
    tab = which
    load(which)
  }

  function action(a: string) {
    const key = `admin.action.${a}`
    const label = t(key)
    return label === key ? a : label
  }

  function details(r: AuditRow) {
    const d = { ...r.details }
    const ids = d.context_message_ids as string[] | undefined
    if (ids) d.context_message_ids = t('admin.audit.ids', { n: ids.length })
    return Object.entries(d)
      .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
      .join(' · ')
  }

  async function saveSettings(e: SubmitEvent) {
    e.preventDefault()
    if (!settings) return
    try {
      settings = await api<Settings>('/api/admin/settings', {
        method: 'PATCH',
        body: { name: settings.name, language: settings.language, server_location: settings.server_location, interest_rate_pct: Number(settings.interest_rate_pct), retention: settings.retention, llm_provider: settings.llm_provider || null },
      })
      saved = t('admin.saved')
      setTimeout(() => (saved = ''), 2000)
      if (store.me) {
        store.me.org_name = settings.name
        store.me.server_location = settings.server_location
        store.me.org_language = settings.language
        if (!store.me.locale) {
          store.me.language = settings.language
          setLanguage(settings.language)
        }
      }
      store.loadAgents()
    } catch (err) {
      error = (err as Error).message
    }
  }

  async function runRetention() {
    const r = await api<Record<string, number>>('/api/admin/retention/run', { method: 'POST' })
    saved = Object.keys(r).length ? t('admin.retention.deleted', { what: Object.entries(r).map(([k, v]) => `${v} ${k}`).join(', ') }) : t('admin.retention.nothing')
  }

  async function addUser(e: SubmitEvent) {
    e.preventDefault()
    error = ''
    try {
      await api('/api/admin/users', { body: newUser })
      newUser = { email: '', name: '', password: '', role_label: '', is_admin: false }
      await load('people')
      await store.loadPeople()
    } catch (err) {
      error = (err as Error).message
    }
  }

  async function patchUser(u: UserRow, body: Partial<UserRow>) {
    await api(`/api/admin/users/${u.id}`, { method: 'PATCH', body })
    await load('people')
  }

  async function exportGuest(g: GuestRow) {
    const data = await api(`/api/admin/guests/${g.id}/export`)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `guest-${(g.name ?? g.id).replace(/\s+/g, '-').toLowerCase()}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  let confirmDelete = $state<string | null>(null)
  async function deleteGuest(g: GuestRow) {
    if (confirmDelete !== g.id) {
      confirmDelete = g.id
      return
    }
    confirmDelete = null
    await api(`/api/admin/guests/${g.id}`, { method: 'DELETE' })
    await load('guests')
  }

  async function addMember(c: ChannelRow, userId: string) {
    if (!userId) return
    await api(`/api/channels/${c.id}/members`, { body: { user_ids: [userId] } })
    await load('channels')
  }

  const names = $derived(Object.fromEntries(users.map((u) => [u.id, u.name])))
</script>

<main class="admin">
  <h1>{t('admin.title')}</h1>
  <p class="hint">{t('admin.intro')}</p>
  <div class="tabs" role="tablist">
    {#each TABS as tb}
      <button role="tab" aria-selected={tab === tb} onclick={() => open(tb)}>{t(`admin.tab.${tb}`)}</button>
    {/each}
  </div>
  {#if error}<p class="error">{error}</p>{/if}

  {#if tab === 'audit'}
    <form class="copy" style="max-width:420px;margin-bottom:12px" onsubmit={(e) => { e.preventDefault(); load('audit') }}>
      <label class="sr" for="af">{t('admin.audit.filter')}</label>
      <select id="af" class="btn" bind:value={filter} onchange={() => load('audit')}>
        {#each FILTERS as f}<option value={f}>{t(`admin.filter.${f || 'all'}`)}</option>{/each}
      </select>
    </form>
    <div class="table-wrap">
      <table>
        <thead><tr><th>{t('admin.audit.when')}</th><th>{t('admin.audit.who')}</th><th>{t('admin.audit.what')}</th><th>{t('admin.audit.details')}</th></tr></thead>
        <tbody>
          {#each audit as r (r.id)}
            <tr><td>{when(r.at)}</td><td>{r.actor_name} <span class="hint">({r.actor_kind})</span></td><td>{action(r.action)}</td><td><code>{details(r)}</code></td></tr>
          {:else}
            <tr><td colspan="4">{t('admin.audit.empty')}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else if tab === 'settings' && settings}
    <form class="grid" onsubmit={saveSettings}>
      <label class="field">{t('admin.set.name')}<input bind:value={settings.name} required /></label>
      <label class="field">{t('admin.set.language')}
        <select bind:value={settings.language}>{#each LANGS as l}<option value={l}>{t(`lang.${l}`)}</option>{/each}</select>
      </label>
      <label class="field">{t('admin.set.location')}<input bind:value={settings.server_location} placeholder="Frankfurt" /></label>
      <label class="field">{t('admin.set.interest')}<input type="number" step="0.01" min="0" max="100" bind:value={settings.interest_rate_pct} /></label>
      <label class="field">{t('admin.set.llm')}
        <select bind:value={settings.llm_provider}>
          <option value={null}>{t('admin.set.llm_default', { name: settings.default_llm_provider })}</option>
          {#each settings.llm_providers as p}<option value={p}>{p === 'anthropic' ? 'Anthropic API' : p === 'openai_compat' ? t('admin.set.llm_self') : p}</option>{/each}
        </select>
      </label>
      <label class="field">{t('admin.set.keep_shared')}<input type="number" min="1" bind:value={settings.retention.shared_days} /></label>
      <label class="field">{t('admin.set.keep_internal')}<input type="number" min="1" bind:value={settings.retention.internal_days} /></label>
      <label class="field">{t('admin.set.keep_audit')}<input type="number" min="1" bind:value={settings.retention.audit_days} /></label>
      <label class="field">{t('admin.set.keep_guests')}<input type="number" min="1" bind:value={settings.retention.guest_days_after_expiry} /></label>
      <div class="row" style="justify-content:flex-start;align-items:center;gap:10px;grid-column:1/-1">
        <button class="btn primary">{t('common.save')}</button>
        <button type="button" class="btn" onclick={runRetention}>{t('admin.set.retention_now')}</button>
        {#if saved}<span class="saved">{saved}</span>{/if}
      </div>
    </form>
    <p class="hint" style="margin-top:14px">{t('admin.set.hint')}</p>
  {:else if tab === 'people'}
    <div class="table-wrap">
      <table>
        <thead><tr><th>{t('admin.people.name')}</th><th>{t('login.email')}</th><th>{t('admin.people.role')}</th><th>{t('admin.people.admin')}</th><th>{t('admin.people.active')}</th></tr></thead>
        <tbody>
          {#each users as u (u.id)}
            <tr>
              <td>{u.name}</td><td>{u.email}</td><td>{u.role_label}</td>
              <td><input type="checkbox" aria-label={t('admin.people.admin')} checked={u.is_admin} disabled={u.id === store.me?.id} onchange={(e) => patchUser(u, { is_admin: (e.currentTarget as HTMLInputElement).checked })} /></td>
              <td><input type="checkbox" aria-label={t('admin.people.active')} checked={u.is_active} disabled={u.id === store.me?.id} onchange={(e) => patchUser(u, { is_active: (e.currentTarget as HTMLInputElement).checked })} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <h2>{t('admin.people.add_title')}</h2>
    <form class="grid" onsubmit={addUser}>
      <label class="field">{t('admin.people.name')}<input bind:value={newUser.name} required /></label>
      <label class="field">{t('login.email')}<input type="email" bind:value={newUser.email} required /></label>
      <label class="field">{t('admin.people.role')}<input bind:value={newUser.role_label} placeholder={t('admin.people.role_example')} /></label>
      <label class="field">{t('admin.people.password')}<input type="password" bind:value={newUser.password} minlength="10" required /></label>
      <label class="check"><input type="checkbox" bind:checked={newUser.is_admin} /> {t('admin.people.admin')}</label>
      <div><button class="btn primary">{t('admin.people.add')}</button></div>
    </form>
  {:else if tab === 'guests'}
    <div class="table-wrap">
      <table>
        <thead><tr><th>{t('admin.guests.guest')}</th><th>{t('admin.guests.channel')}</th><th>{t('admin.guests.messages')}</th><th>{t('admin.guests.link')}</th><th></th></tr></thead>
        <tbody>
          {#each guests as g (g.id)}
            <tr>
              <td>{g.name ?? t('admin.guests.not_opened')}{g.company ? `, ${g.company}` : ''}</td>
              <td>{g.channel_name}</td>
              <td>{g.message_count}</td>
              <td>{g.revoked_at ? t('admin.guests.revoked') : new Date(g.expires_at) < new Date() ? t('admin.guests.expired') : t('admin.guests.valid', { until: when(g.expires_at) })}</td>
              <td style="white-space:nowrap">
                <button class="btn small" onclick={() => exportGuest(g)}>{t('admin.guests.export')}</button>
                <button class="btn small danger" onclick={() => deleteGuest(g)}>{confirmDelete === g.id ? t('msg.really_delete') : t('msg.delete')}</button>
              </td>
            </tr>
          {:else}
            <tr><td colspan="5">{t('admin.guests.none')}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="hint" style="margin-top:12px">{t('admin.guests.hint')}</p>
  {:else if tab === 'rooms'}
    <RoomsEditor />
  {:else if tab === 'channels'}
    <div class="table-wrap">
      <table>
        <thead><tr><th>{t('admin.guests.channel')}</th><th>{t('nc.kind')}</th><th>{t('nc.members')}</th><th>{t('admin.ch.add')}</th></tr></thead>
        <tbody>
          {#each channels as c (c.id)}
            <tr>
              <td>{c.kind === 'internal' ? `#${c.name}` : c.name}</td>
              <td>{c.kind === 'shared' ? t('admin.ch.shared', { partner: c.partner_name }) : t('nc.internal')}</td>
              <td>{c.member_ids.map((id) => names[id] ?? '?').join(', ')}</td>
              <td>
                <label class="sr" for="add-{c.id}">{t('admin.ch.add_member')}</label>
                <select id="add-{c.id}" class="btn small" onchange={(e) => addMember(c, (e.currentTarget as HTMLSelectElement).value)}>
                  <option value="">{t('admin.ch.add_pick')}</option>
                  {#each users.filter((u) => !c.member_ids.includes(u.id) && u.is_active) as u (u.id)}<option value={u.id}>{u.name}</option>{/each}
                </select>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</main>
