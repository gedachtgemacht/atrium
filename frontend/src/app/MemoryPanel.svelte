<script lang="ts">
  import { api } from '../lib/api'
  import { firstName, when } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { AskAnswer, Channel, MemoryEntry } from '../lib/types'
  import { store } from './store.svelte'

  let { channelId, shared }: { channelId: string; shared: Channel } = $props()
  let editing = $state<string | null>(null)
  let draft = $state({ text: '', kind: 'decided', owner_name: '', due_label: '' })
  let question = $state('')
  let answer = $state<AskAnswer | null>(null)
  let asking = $state(false)

  const entries = $derived(store.memory[channelId] ?? [])
  const groups = $derived([
    { kind: 'decided', title: 'Decided', empty: 'Nothing decided yet.' },
    { kind: 'open', title: 'Open', empty: 'Nothing open. Questions from the customer channel land here once you pull them in.' },
    { kind: 'committed', title: 'Promised', empty: 'No promises yet.' },
  ])
  const guestName = $derived(firstName(store.details[shared.id]?.guests.find((g) => g.joined)?.name ?? 'the customer'))
  const suggestions = $derived(["What's still open?", `What does ${guestName} want?`, 'What did we decide?', 'Who promised what?'])

  $effect(() => {
    if (store.globalQuestion) {
      question = store.globalQuestion
      store.globalQuestion = ''
      ask()
    }
  })

  function meta(e: MemoryEntry) {
    if (e.status === 'done') return `${e.done_note || 'Done'}${e.done_at ? `, ${when(e.done_at)}` : ''}`
    const bits = []
    if (e.owner_name) bits.push(e.owner_name)
    if (e.due_label) bits.push(e.due_label)
    if (e.source_label) {
      const [who, at] = e.source_label.split(', ')
      if (!e.owner_name || firstName(who) !== firstName(e.owner_name)) bits.push(`from ${who}`)
      if (at) bits.push(when(at))
    }
    return bits.join(', ')
  }

  function jump(e: MemoryEntry) {
    if (!e.source_message_id) return
    store.backroomTab = 'work'
    setTimeout(() => store.flash(e.source_message_id!), 80)
  }

  function edit(e: MemoryEntry) {
    editing = e.id
    draft = { text: e.text, kind: e.kind, owner_name: e.owner_name, due_label: e.due_label }
  }

  async function save(e: MemoryEntry, ev: SubmitEvent) {
    ev.preventDefault()
    await api(`/api/memory/${e.id}`, { method: 'PATCH', body: draft })
    editing = null
    await store.loadMemory(channelId)
  }

  async function toggleDone(e: MemoryEntry) {
    await api(`/api/memory/${e.id}`, { method: 'PATCH', body: { status: e.status === 'done' ? 'active' : 'done' } })
    await store.loadMemory(channelId)
  }

  async function remove(e: MemoryEntry) {
    await api(`/api/memory/${e.id}`, { method: 'DELETE' })
    await store.loadMemory(channelId)
  }

  async function ask(ev?: SubmitEvent) {
    ev?.preventDefault()
    const q = question.trim()
    if (!q) return
    asking = true
    try {
      answer = await api<AskAnswer>('/api/ask', { body: { question: q, channel_id: channelId } })
    } catch (e) {
      store.toast((e as Error).message)
    } finally {
      asking = false
    }
  }

  function showSource(s: AskAnswer['sources'][number]) {
    if (s.kind === 'message') {
      store.backroomTab = 'work'
      setTimeout(() => store.flash(s.id), 80)
    } else {
      const e = entries.find((x) => x.id === s.id)
      if (e?.source_message_id) jump(e)
    }
  }
</script>

<div class="back-body mem" role="tabpanel">
  <p class="mem-sub">Kept from the backroom and from everything you pull in. A click shows the source.</p>
  {#each groups as g (g.kind)}
    {@const list = entries.filter((e) => e.kind === g.kind)}
    <div class="mem-group">
      <h3>{g.title}</h3>
      {#if list.length}
        <ul class="mem-list">
          {#each list as e (e.id)}
            <li class:done={e.status === 'done'}>
              {#if editing === e.id}
                <form class="mem-edit" onsubmit={(ev) => save(e, ev)}>
                  <label class="sr" for="t-{e.id}">Text</label>
                  <input id="t-{e.id}" bind:value={draft.text} required maxlength="500" />
                  <div class="row">
                    <label class="sr" for="k-{e.id}">Kind</label>
                    <select id="k-{e.id}" bind:value={draft.kind}>
                      <option value="decided">Decided</option><option value="open">Open</option><option value="committed">Promised</option>
                    </select>
                    <input aria-label="Owner" placeholder="Owner" bind:value={draft.owner_name} />
                    <input aria-label="Due" placeholder="Due, like by Friday" bind:value={draft.due_label} />
                  </div>
                  <div class="row"><button class="btn small primary">Save</button><button type="button" class="btn small" onclick={() => (editing = null)}>Cancel</button></div>
                </form>
              {:else}
                <button class="mem-item" onclick={() => jump(e)} disabled={!e.source_message_id}>
                  <span class="t">{e.text}</span>
                  <span class="m">{meta(e)}</span>
                </button>
                <span class="mem-tools">
                  {#if e.kind !== 'decided'}
                    <button title={e.status === 'done' ? 'Mark as not done' : 'Mark as done'} aria-label={e.status === 'done' ? 'Mark as not done' : 'Mark as done'} onclick={() => toggleDone(e)}>{@html icons.check(14)}</button>
                  {/if}
                  <button title="Edit" aria-label="Edit" onclick={() => edit(e)}>{@html icons.pen(13)}</button>
                  <button title="Delete" aria-label="Delete" onclick={() => remove(e)}>{@html icons.trash()}</button>
                </span>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="empty">{g.empty}</p>
      {/if}
    </div>
  {/each}

  <div class="ask">
    <h3><label for="ask-{channelId}">Ask the backroom</label></h3>
    <form onsubmit={ask}>
      <input id="ask-{channelId}" type="text" placeholder="What's still open?" autocomplete="off" bind:value={question} />
      <button class="btn" type="submit" disabled={asking}>Ask</button>
    </form>
    <div class="suggest">
      {#each suggestions as s}<button type="button" onclick={() => { question = s; ask() }}>{s}</button>{/each}
    </div>
    {#if asking}<p class="hint" style="margin-top:8px">Thinking</p>{/if}
    {#if answer}
      <div class="answer" aria-live="polite">
        <p class="q">{answer.question}</p>
        <p>{answer.answer}</p>
        {#if answer.sources.length}
          <div class="srcs">
            {#each answer.sources as s, i}
              <button class="link-btn" type="button" onclick={() => showSource(s)}>{answer.sources.length > 1 ? `Source ${i + 1}` : 'Show source'}</button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>
