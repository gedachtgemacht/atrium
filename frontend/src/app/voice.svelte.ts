import type { RemoteParticipant, RemoteTrack, Room } from 'livekit-client'

/** Voice in rooms over the self hosted LiveKit server, plus the microphone feed for room notes. */
class Voice {
  room: Room | null = null
  speaking = $state<string[]>([])
  connected = $state(false)
  error = $state('')
  muted = $state(false)
  #notes: { ctx: AudioContext; stream: MediaStream; node: AudioWorkletNode } | null = null
  #elements = new Map<string, HTMLMediaElement[]>()
  #generation = 0

  async join(url: string, token: string) {
    const gen = ++this.#generation
    await this.#disconnect()
    if (gen !== this.#generation) return
    this.error = ''
    // Loaded only when someone actually joins a room with voice.
    const { Room, RoomEvent, Track } = await import('livekit-client')
    const room = new Room({ adaptiveStream: true, dynacast: true })
    this.room = room
    room.on(RoomEvent.ActiveSpeakersChanged, (s) => (this.speaking = s.map((p) => p.identity)))
    room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, _pub, p: RemoteParticipant) => {
      if (track.kind !== Track.Kind.Audio) return
      const el = track.attach()
      el.hidden = true
      document.body.appendChild(el)
      this.#elements.set(p.identity, [...(this.#elements.get(p.identity) ?? []), el])
    })
    room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack, _pub, p: RemoteParticipant) => {
      const gone = track.detach()
      gone.forEach((el) => el.remove())
      this.#elements.set(p.identity, (this.#elements.get(p.identity) ?? []).filter((el) => !gone.includes(el)))
    })
    // Someone left the room: LiveKit doesn't always unsubscribe their tracks first, so drop their audio here.
    room.on(RoomEvent.ParticipantDisconnected, (p: RemoteParticipant) => {
      ;(this.#elements.get(p.identity) ?? []).forEach((el) => el.remove())
      this.#elements.delete(p.identity)
    })
    room.on(RoomEvent.Disconnected, () => (this.connected = false))
    try {
      await room.connect(url, token)
      if (gen !== this.#generation) {
        await room.disconnect()
        return
      }
      this.connected = true
      await room.localParticipant.setMicrophoneEnabled(!this.muted)
    } catch (e) {
      this.error = 'Voice is not available right now.'
      this.connected = false
    }
  }

  async setMuted(m: boolean) {
    this.muted = m
    try {
      await this.room?.localParticipant.setMicrophoneEnabled(!m)
    } catch {}
  }

  async leave() {
    this.#generation++
    await this.#disconnect()
  }

  async #disconnect() {
    this.speaking = []
    this.connected = false
    const r = this.room
    this.room = null
    if (r) await r.disconnect()
    this.#elements.forEach((els) => els.forEach((el) => el.remove()))
    this.#elements.clear()
  }

  /** While notes are on in your room, your own browser sends your own microphone, nothing else. */
  async startNotes(send: (chunk: ArrayBuffer) => void) {
    if (this.#notes) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
      const ctx = new AudioContext({ sampleRate: 16000 })
      await ctx.audioWorklet.addModule('/pcm-worklet.js')
      const src = ctx.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(ctx, 'pcm-collector')
      let buf: number[] = []
      node.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        if (this.muted) return
        for (const v of ev.data) buf.push(v)
        if (buf.length >= 8000) {
          const out = new Int16Array(buf.length)
          for (let i = 0; i < buf.length; i++) out[i] = Math.max(-1, Math.min(1, buf[i])) * 0x7fff
          buf = []
          send(out.buffer)
        }
      }
      src.connect(node)
      this.#notes = { ctx, stream, node }
    } catch {
      this.error = 'No microphone access, so notes can\'t hear you.'
    }
  }

  stopNotes() {
    const n = this.#notes
    this.#notes = null
    if (!n) return
    n.node.disconnect()
    n.stream.getTracks().forEach((t) => t.stop())
    n.ctx.close()
  }
}

export const voice = new Voice()
