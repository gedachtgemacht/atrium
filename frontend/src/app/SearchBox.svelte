<script lang="ts">
  import { api } from '../lib/api'
  import { time } from '../lib/format'
  import { icons } from '../lib/icons'
  import type { AskAnswer, Message } from '../lib/types'
  import { store } from './store.svelte'

  type Hit = { message: Message; channel_name: string; channel_kind: string }
  let q = $state('')
  let open = $state(false)
  let hits = $state<Hit[]>([])
  let answer = $state<AskAnswer | null>(null)
  let asking = $state(false)
  let timer: ReturnType<typeof setTimeout> | undefined

  function onInput() {
    answer = null
    clearTimeout(timer)
    if (!q.trim()) {
      hits = []
      return
    }
    timer = setTimeout(async () => {
      hits = await api<Hit[]>(`/api/search?q=${encodeURIComponent(q.trim())}`)
      open = true
    }, 220)
  }

  async function ask(e?: SubmitEvent) {
    e?.preventDefault()
    const question = q.trim()
    if (!question) return
    const shared = store.current?.kind === 'shared' ? store.current : null
    if (shared?.backroom_id) {
      // Ask the backroom next to the channel you're in, like in the mockup.
      store.globalQuestion = question
      store.backroomTab = 'memory'
      store.backroomOpen = true
      open = false
      return
    }
    asking = true
    open = true
    try {
      answer = await api<AskAnswer>('/api/ask', { body: { question } })
    } finally {
      asking = false
    }
  }

  function jump(channelId: string, messageId: string) {
    const ch = store.channel(channelId)
    const target = ch?.kind === 'backroom' ? ch.backroom_for_id! : channelId
    open = false
    store.go(target)
    if (ch?.kind === 'backroom') {
      store.backroomTab = 'work'
      store.backroomOpen = true
    }
    setTimeout(() => store.flash(messageId), 350)
  }

  function where(h: Hit) {
    if (h.channel_kind === 'backroom') return h.channel_name
    if (h.channel_kind === 'shared') return `${h.channel_name}, customer channel`
    return `#${h.channel_name}`
  }
</script>

<form class="ask-global" role="search" onsubmit={ask}>
  {@html icons.search()}
  <label class="sr" for="globalInput">Search or ask</label>
  <input id="globalInput" type="search" placeholder="Search or ask" autocomplete="off" bind:value={q} oninput={onInput}
    onfocus={() => q && (open = true)} onblur={() => setTimeout(() => (open = false), 200)} />
  {#if open && q.trim()}
    <div class="search-pop">
      {#if hits.length}
        <h3>Messages you can read</h3>
        {#each hits as h (h.message.id)}
          <button type="button" class="search-hit" onclick={() => jump(h.message.channel_id, h.message.id)}>
            <span class="where">{where(h)} · {h.message.author.name} · {time(h.message.created_at)}</span>
            <span class="what">{h.message.body}</span>
          </button>
        {/each}
      {:else}
        <h3>No messages found</h3>
      {/if}
      <button type="submit" class="search-ask">{@html icons.lock()} Ask the backroom: “{q.trim()}”</button>
      {#if asking}<p class="hint">Thinking</p>{/if}
      {#if answer}
        <div class="answer">
          <p class="q">{answer.question}</p>
          <p>{answer.answer}</p>
          <div class="srcs">
            {#each answer.sources as s}
              <button type="button" class="link-btn" onclick={() => s.kind === 'message' ? jump(s.channel_id, s.id) : jump(s.channel_id, s.id)}>Show source</button>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  {/if}
</form>
