import { api, socketUrl } from '../lib/api'
import type { Agent, Channel, Draft, Floor, Me, MemoryEntry, Message, Person, PresenceRoom, Room, RoomsPlan, WorkResult } from '../lib/types'
import { voice } from './voice.svelte'

type Route = { view: 'channel'; id: string | null } | { view: 'admin' }

function parseHash(): Route {
  const h = location.hash.replace(/^#\/?/, '')
  if (h === 'admin') return { view: 'admin' }
  const m = h.match(/^c\/([0-9a-f-]{36})/)
  return { view: 'channel', id: m ? m[1] : null }
}

class Store {
  me = $state<Me | null>(null)
  channels = $state<Channel[]>([])
  details = $state<Record<string, Channel>>({})
  agents = $state<Agent[]>([])
  rooms = $state<Room[]>([])
  floors = $state<Floor[]>([])
  people = $state<Record<string, Person>>({})
  online = $state<string[]>([])
  presence = $state<PresenceRoom[]>([])
  route = $state<Route>(parseHash())
  messages = $state<Record<string, Message[]>>({})
  drafts = $state<Draft[]>([])
  memory = $state<Record<string, MemoryEntry[]>>({})
  busy = $state<Record<string, boolean>>({})
  toastText = $state('')
  connected = $state(false)
  flashId = $state<string | null>(null)
  composerFlash = $state(0)
  backroomTab = $state<'work' | 'memory'>('work')
  backroomOpen = $state(false)
  railOpen = $state(false)
  globalQuestion = $state('')

  #ws: WebSocket | null = null
  #outbox: unknown[] = []
  #retry = 0
  #toastTimer: ReturnType<typeof setTimeout> | undefined

  get current(): Channel | null {
    if (this.route.view !== 'channel') return null
    const id = this.route.id
    return this.channels.find((c) => c.id === id) ?? null
  }

  get myRoom(): PresenceRoom | null {
    const me = this.me?.id
    return this.presence.find((r) => r.people.some((p) => p.user_id === me)) ?? null
  }

  channel(id: string | null | undefined): Channel | undefined {
    return this.channels.find((c) => c.id === id)
  }

  async start() {
    window.addEventListener('hashchange', () => {
      this.route = parseHash()
      this.railOpen = false
      this.backroomOpen = false
    })
    await Promise.all([this.loadChannels(), this.loadAgents(), this.loadRooms(), this.loadPeople(), this.loadDrafts()])
    if (this.route.view === 'channel' && !this.current) {
      const first = this.channels.find((c) => c.kind === 'shared') ?? this.channels.find((c) => c.kind === 'internal')
      if (first) this.go(first.id)
    }
    this.connect()
  }

  go(channelId: string) {
    location.hash = `#/c/${channelId}`
  }

  toast(text: string) {
    this.toastText = text
    clearTimeout(this.#toastTimer)
    this.#toastTimer = setTimeout(() => (this.toastText = ''), 3500)
  }

  async loadChannels() {
    this.channels = await api<Channel[]>('/api/channels')
  }
  async loadDetail(id: string) {
    this.details[id] = await api<Channel>(`/api/channels/${id}`)
  }
  async loadAgents() {
    this.agents = await api<Agent[]>('/api/agents')
  }
  async loadRooms() {
    this.setPlan(await api<RoomsPlan>('/api/rooms'))
  }
  setPlan(p: RoomsPlan) {
    this.rooms = p.rooms
    this.floors = p.floors
  }
  async loadPeople() {
    const list = await api<Person[]>('/api/users')
    this.people = Object.fromEntries(list.map((p) => [p.id, p]))
  }
  async loadDrafts() {
    this.drafts = await api<Draft[]>('/api/drafts')
  }
  async loadMessages(channelId: string) {
    this.messages[channelId] = await api<Message[]>(`/api/channels/${channelId}/messages`)
  }
  async loadMemory(channelId: string) {
    this.memory[channelId] = await api<MemoryEntry[]>(`/api/channels/${channelId}/memory`)
  }
  async markRead(channelId: string) {
    const ch = this.channel(channelId)
    if (ch) ch.unread = 0
    try {
      await api(`/api/channels/${channelId}/read`, { method: 'POST' })
    } catch {}
  }

  upsertMessage(m: Message) {
    const list = this.messages[m.channel_id]
    if (!list) return false
    const i = list.findIndex((x) => x.id === m.id)
    if (i >= 0) list[i] = m
    else list.push(m)
    return i < 0
  }

  upsertWork(w: WorkResult) {
    const list = this.messages[w.channel_id]
    if (!list) return
    for (const m of list) {
      const i = m.work_results.findIndex((x) => x.id === w.id)
      if (i >= 0) m.work_results[i] = w
      else if (m.id === w.message_id) m.work_results.push(w)
    }
  }

  flash(id: string) {
    this.flashId = null
    queueMicrotask(() => (this.flashId = id))
    setTimeout(() => {
      if (this.flashId === id) this.flashId = null
    }, 1400)
  }

  connect() {
    const ws = new WebSocket(socketUrl('/ws'))
    this.#ws = ws
    ws.onopen = () => {
      this.connected = true
      this.#retry = 0
      for (const m of this.#outbox.splice(0)) ws.send(JSON.stringify(m))
      // Catch up on whatever happened while we were away.
      for (const id of Object.keys(this.messages)) this.loadMessages(id)
      this.loadChannels()
      this.loadDrafts()
    }
    ws.onmessage = (ev) => this.onEvent(JSON.parse(ev.data))
    ws.onclose = (ev) => {
      this.connected = false
      this.#ws = null
      voice.leave()
      if (ev.code === 4401) {
        location.reload()
        return
      }
      const delay = Math.min(15000, 500 * 2 ** this.#retry++)
      setTimeout(() => this.connect(), delay)
    }
  }

  send(data: unknown) {
    // Clicks that happen while the socket (re)connects go out as soon as it is open.
    if (this.#ws?.readyState === WebSocket.OPEN) this.#ws.send(JSON.stringify(data))
    else this.#outbox.push(data)
  }

  sendAudio(chunk: ArrayBuffer) {
    if (this.#ws?.readyState === WebSocket.OPEN) this.#ws.send(chunk)
  }

  onEvent(e: any) {
    switch (e.type) {
      case 'message.created': {
        const m = e.message as Message
        const isNew = this.upsertMessage(m)
        const ch = this.channel(m.channel_id)
        const viewing = this.route.view === 'channel' && (this.route.id === m.channel_id || this.current?.backroom_id === m.channel_id)
        if (ch && !viewing && m.author.id !== this.me?.id && (isNew || !this.messages[m.channel_id])) ch.unread += 1
        if (viewing && document.visibilityState === 'visible') this.markRead(m.channel_id)
        break
      }
      case 'message.updated':
        this.upsertMessage(e.message)
        break
      case 'message.deleted': {
        const list = this.messages[e.channel_id]
        if (list) this.messages[e.channel_id] = list.filter((m) => m.id !== e.message_id)
        break
      }
      case 'work_result.updated':
        this.upsertWork(e.work_result)
        this.loadAgents()
        break
      case 'draft.updated':
        this.loadDrafts()
        this.loadAgents()
        break
      case 'memory.updated':
        if (this.memory[e.channel_id]) this.loadMemory(e.channel_id)
        break
      case 'agent.status':
        this.busy[`${e.slug}:${e.channel_id}`] = e.busy
        this.loadAgents()
        break
      case 'presence.state':
        this.online = e.online
        this.presence = e.rooms
        this.loadAgents()
        break
      case 'room.voice':
        if (e.url && e.token) voice.join(e.url, e.token)
        else voice.leave()
        break
      case 'rooms.updated':
        this.loadRooms()
        break
      case 'error':
        if (e.detail) this.toast(e.detail)
        break
      case 'channels.updated':
        this.loadChannels()
        for (const id of Object.keys(this.details)) this.loadDetail(id)
        break
    }
  }
}

export const store = new Store()
