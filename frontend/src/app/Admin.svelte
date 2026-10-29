<script lang="ts">
  import { onMount } from 'svelte'
  import { api } from '../lib/api'
  import { when } from '../lib/format'
  import RoomsEditor from './RoomsEditor.svelte'
  import { store } from './store.svelte'

  type Tab = 'audit' | 'settings' | 'people' | 'guests' | 'channels' | 'rooms'
  type AuditRow = { id: string; at: string; actor_kind: string; actor_name: string; action: string; subject_id: string | null; details: Record<string, unknown> }
  type Settings = { name: string; server_location: string; interest_rate_pct: string; retention: Record<string, number | null>; llm_provider: string | null; llm_providers: string[]; default_llm_provider: string }
  type UserRow = { id: string; email: string; name: string; role_label: string; is_admin: boolean; is_active: boolean }
  type GuestRow = { id: string; name: string | null; company: string; channel_name: string; created_at: string; expires_at: string; revoked_at: string | null; message_count: number }
  type ChannelRow = { id: string; kind: string; name: string; partner_name: string; member_ids: string[] }

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

  const actions: Record<string, string> = {
    'message.pulled': 'Pulled into backroom',
    'draft.created': 'Draft placed in composer',
    'draft.sent': 'Draft sent by a person',
    'draft.discarded': 'Draft discarded',
    'draft.attachment_removed': 'Draft attachment removed',
    'llm.call': 'LLM call',
    'guest.invited': 'Guest invited',
    'guest.joined': 'Guest joined',
    'guest.signed_in': 'Guest opened link',
    'guest.revoked': 'Guest access revoked',
    'guest.exported': 'Guest data exported',
    'guest.deleted': 'Guest deleted',
    'memory.created': 'Memory added',
    'memory.edited': 'Memory edited',
    'memory.deleted': 'Memory deleted',
    'work_result.edited': 'Prices changed',
    'settings.changed': 'Settings changed',
    'retention.applied': 'Retention applied',
    'rooms.created': 'Room added',
    'rooms.changed': 'Room changed',
    'rooms.deleted': 'Room deleted',
    'rooms.floors_changed': 'Floors changed',
    'message.edited': 'Message edited',
    'message.deleted': 'Message deleted',
  }

  async function load(t: Tab) {
    error = ''
    if (t === 'audit') audit = await api<AuditRow[]>(`/api/admin/audit?limit=200${filter ? `&action=${encodeURIComponent(filter)}` : ''}`)
    if (t === 'settings') settings = await api<Settings>('/api/admin/settings')
    if (t === 'people') users = await api<UserRow[]>('/api/admin/users')
    if (t === 'guests') guests = await api<GuestRow[]>('/api/admin/guests')
    if (t === 'channels') {
      ;[channels, users] = await Promise.all([api<ChannelRow[]>('/api/admin/channels'), api<UserRow[]>('/api/admin/users')])
    }
  }

  onMount(() => load(tab))

  function open(t: Tab) {
    tab = t
    load(t)
  }

  function details(r: AuditRow) {
    const d = { ...r.details }
    const ids = d.context_message_ids as string[] | undefined
    if (ids) d.context_message_ids = `${ids.length} message ids`
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
        body: { name: settings.name, server_location: settings.server_location, interest_rate_pct: Number(settings.interest_rate_pct), retention: settings.retention, llm_provider: settings.llm_provider || null },
      })
      saved = 'Saved'
      setTimeout(() => (saved = ''), 2000)
      if (store.me) {
        store.me.org_name = settings.name
        store.me.server_location = settings.server_location
      }
    } catch (err) {
      error = (err as Error).message
    }
  }

  async function runRetention() {
    const r = await api<Record<string, number>>('/api/admin/retention/run', { method: 'POST' })
    saved = Object.keys(r).length ? `Deleted: ${Object.entries(r).map(([k, v]) => `${v} ${k}`).join(', ')}` : 'Nothing to delete'
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
  <h1>Admin</h1>
  <p class="hint">Audit log, retention, guest data and the language model. Admins don't get to read channels they aren't in.</p>
  <div class="tabs" role="tablist">
    {#each [['audit', 'Audit log'], ['settings', 'Settings'], ['people', 'People'], ['guests', 'Guests'], ['channels', 'Channels'], ['rooms', 'Rooms']] as [t, label]}
      <button role="tab" aria-selected={tab === t} onclick={() => open(t as Tab)}>{label}</button>
    {/each}
  </div>
  {#if error}<p class="error">{error}</p>{/if}

  {#if tab === 'audit'}
    <form class="copy" style="max-width:420px;margin-bottom:12px" onsubmit={(e) => { e.preventDefault(); load('audit') }}>
      <label class="sr" for="af">Filter</label>
      <select id="af" class="btn" bind:value={filter} onchange={() => load('audit')}>
        <option value="">Everything</option>
        <option value="message.pulled">Pulled into backroom</option>
        <option value="draft">Drafts</option>
        <option value="llm.call">LLM calls</option>
        <option value="guest">Guests</option>
        <option value="memory">Memory</option>
        <option value="settings">Settings</option>
      </select>
    </form>
    <div class="table-wrap">
      <table>
        <thead><tr><th>When</th><th>Who</th><th>What</th><th>Details</th></tr></thead>
        <tbody>
          {#each audit as r (r.id)}
            <tr><td>{when(r.at)}</td><td>{r.actor_name} <span class="hint">({r.actor_kind})</span></td><td>{actions[r.action] ?? r.action}</td><td><code>{details(r)}</code></td></tr>
          {:else}
            <tr><td colspan="4">Nothing logged yet.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else if tab === 'settings' && settings}
    <form class="grid" onsubmit={saveSettings}>
      <label class="field">Company name<input bind:value={settings.name} required /></label>
      <label class="field">Server location (shown to guests)<input bind:value={settings.server_location} placeholder="Frankfurt" /></label>
      <label class="field">Interest rate in %<input type="number" step="0.01" min="0" max="100" bind:value={settings.interest_rate_pct} /></label>
      <label class="field">Language model
        <select bind:value={settings.llm_provider}>
          <option value={null}>Server default ({settings.default_llm_provider})</option>
          {#each settings.llm_providers as p}<option value={p}>{p === 'anthropic' ? 'Anthropic API' : p === 'openai_compat' ? 'Self hosted (OpenAI compatible)' : p}</option>{/each}
        </select>
      </label>
      <label class="field">Keep customer channels (days, empty = forever)<input type="number" min="1" bind:value={settings.retention.shared_days} /></label>
      <label class="field">Keep internal channels and backrooms (days)<input type="number" min="1" bind:value={settings.retention.internal_days} /></label>
      <label class="field">Keep audit log (days)<input type="number" min="1" bind:value={settings.retention.audit_days} /></label>
      <label class="field">Delete guests after their link ended (days)<input type="number" min="1" bind:value={settings.retention.guest_days_after_expiry} /></label>
      <div class="row" style="justify-content:flex-start;align-items:center;gap:10px;grid-column:1/-1">
        <button class="btn primary">Save</button>
        <button type="button" class="btn" onclick={runRetention}>Apply retention now</button>
        {#if saved}<span class="saved">{saved}</span>{/if}
      </div>
    </form>
    <p class="hint" style="margin-top:14px">API keys stay in the server's environment. Retention runs once a day.</p>
  {:else if tab === 'people'}
    <div class="table-wrap">
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Admin</th><th>Active</th></tr></thead>
        <tbody>
          {#each users as u (u.id)}
            <tr>
              <td>{u.name}</td><td>{u.email}</td><td>{u.role_label}</td>
              <td><input type="checkbox" aria-label="Admin" checked={u.is_admin} disabled={u.id === store.me?.id} onchange={(e) => patchUser(u, { is_admin: (e.currentTarget as HTMLInputElement).checked })} /></td>
              <td><input type="checkbox" aria-label="Active" checked={u.is_active} disabled={u.id === store.me?.id} onchange={(e) => patchUser(u, { is_active: (e.currentTarget as HTMLInputElement).checked })} /></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <h2>Add a person</h2>
    <form class="grid" onsubmit={addUser}>
      <label class="field">Name<input bind:value={newUser.name} required /></label>
      <label class="field">Email<input type="email" bind:value={newUser.email} required /></label>
      <label class="field">Role<input bind:value={newUser.role_label} placeholder="Sales" /></label>
      <label class="field">First password (10+ characters)<input type="password" bind:value={newUser.password} minlength="10" required /></label>
      <label class="check"><input type="checkbox" bind:checked={newUser.is_admin} /> Admin</label>
      <div><button class="btn primary">Add</button></div>
    </form>
  {:else if tab === 'guests'}
    <div class="table-wrap">
      <table>
        <thead><tr><th>Guest</th><th>Channel</th><th>Messages</th><th>Link</th><th></th></tr></thead>
        <tbody>
          {#each guests as g (g.id)}
            <tr>
              <td>{g.name ?? 'Not opened yet'}{g.company ? `, ${g.company}` : ''}</td>
              <td>{g.channel_name}</td>
              <td>{g.message_count}</td>
              <td>{g.revoked_at ? 'Revoked' : new Date(g.expires_at) < new Date() ? 'Expired' : `Valid until ${when(g.expires_at)}`}</td>
              <td style="white-space:nowrap">
                <button class="btn small" onclick={() => exportGuest(g)}>Export</button>
                <button class="btn small danger" onclick={() => deleteGuest(g)}>{confirmDelete === g.id ? 'Really delete?' : 'Delete'}</button>
              </td>
            </tr>
          {:else}
            <tr><td colspan="5">No guests yet.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="hint" style="margin-top:12px">Delete removes the guest, their messages, the backroom copies of them and their files.</p>
  {:else if tab === 'rooms'}
    <RoomsEditor />
  {:else if tab === 'channels'}
    <div class="table-wrap">
      <table>
        <thead><tr><th>Channel</th><th>Kind</th><th>Members</th><th>Add</th></tr></thead>
        <tbody>
          {#each channels as c (c.id)}
            <tr>
              <td>{c.kind === 'internal' ? `#${c.name}` : c.name}</td>
              <td>{c.kind === 'shared' ? `With ${c.partner_name}, plus backroom` : 'Internal'}</td>
              <td>{c.member_ids.map((id) => names[id] ?? '?').join(', ')}</td>
              <td>
                <label class="sr" for="add-{c.id}">Add member</label>
                <select id="add-{c.id}" class="btn small" onchange={(e) => addMember(c, (e.currentTarget as HTMLSelectElement).value)}>
                  <option value="">Add …</option>
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
