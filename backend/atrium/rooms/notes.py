"""Room notes. Only while someone in the room switched them on, and everybody in the room sees it.

While notes are on, each browser in the room sends its own microphone audio
(16 kHz mono PCM16) over its WebSocket. Audio stays in memory, is transcribed
locally with faster-whisper and then dropped. When notes go off, the notes
agent turns the transcript into a summary in the room's internal channel and
the transcript is dropped too. Raw audio and raw transcripts are never stored.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

log = logging.getLogger("atrium.notes")

SAMPLE_RATE = 16000
CHUNK_SECONDS = 12
MAX_BUFFER_SECONDS = 30


class Transcriber:
    async def transcribe(self, pcm16: bytes, hint: str = "") -> str:
        raise NotImplementedError


class FakeTranscriber(Transcriber):
    """Tests: the "audio" is UTF-8 text."""

    async def transcribe(self, pcm16: bytes, hint: str = "") -> str:
        return pcm16.decode("utf-8", errors="ignore")


class WhisperTranscriber(Transcriber):
    def __init__(self, model: str, language: str = ""):
        self._name = model
        self._language = language or None
        self._model = None
        self._lock = asyncio.Lock()

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self._name, device="cpu", compute_type="int8")
        return self._model

    def _run(self, pcm16: bytes, hint: str) -> str:
        import numpy as np

        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._load().transcribe(audio, language=self._language, vad_filter=True, initial_prompt=hint or None)
        return " ".join(s.text.strip() for s in segments).strip()

    async def transcribe(self, pcm16: bytes, hint: str = "") -> str:
        async with self._lock:
            return await asyncio.to_thread(self._run, pcm16, hint)


@dataclass
class Session:
    room_id: uuid.UUID
    started_by: str
    buffers: dict[uuid.UUID, bytearray] = field(default_factory=dict)
    names: dict[uuid.UUID, str] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    pending: set = field(default_factory=set)
    vocabulary: list[str] = field(default_factory=list)


class NotesService:
    def __init__(self, state, transcriber: Transcriber):
        self.state = state
        self.transcriber = transcriber
        self.sessions: dict[uuid.UUID, Session] = {}

    def active(self, room_id: uuid.UUID) -> bool:
        return room_id in self.sessions

    def start(self, room_id: uuid.UUID, by_name: str, vocabulary: list[str] | None = None) -> None:
        self.sessions.setdefault(room_id, Session(room_id=room_id, started_by=by_name, vocabulary=vocabulary or []))

    def feed(self, room_id: uuid.UUID, user_id: uuid.UUID, name: str, chunk: bytes) -> None:
        s = self.sessions.get(room_id)
        if s is None:
            return  # notes are off: audio is dropped on arrival
        buf = s.buffers.setdefault(user_id, bytearray())
        s.names[user_id] = name
        buf.extend(chunk)
        if len(buf) > MAX_BUFFER_SECONDS * SAMPLE_RATE * 2:
            del buf[: len(buf) - MAX_BUFFER_SECONDS * SAMPLE_RATE * 2]
        if len(buf) >= CHUNK_SECONDS * SAMPLE_RATE * 2:
            self._flush(s, user_id)

    def add_line(self, room_id: uuid.UUID, name: str, text: str) -> None:
        s = self.sessions.get(room_id)
        if s is not None and text.strip():
            s.lines.append(f"{name}: {text.strip()}")

    def _flush(self, s: Session, user_id: uuid.UUID) -> None:
        data = bytes(s.buffers.get(user_id, b""))
        s.buffers[user_id] = bytearray()
        if not data:
            return
        name = s.names.get(user_id, "Someone")
        # Colleagues' names help whisper spell them right.
        hint = "Names: " + ", ".join(dict.fromkeys(list(s.names.values()) + s.vocabulary)) + "."

        async def work():
            try:
                text = await self.transcriber.transcribe(data, hint)
            except Exception:
                log.exception("transcription failed")
                return
            if text:
                s.lines.append(f"{name}: {text}")

        task = self.state.tasks.spawn(work(), name="notes:transcribe")
        s.pending.add(task)
        task.add_done_callback(s.pending.discard)

    async def stop(self, room_id: uuid.UUID) -> None:
        s = self.sessions.pop(room_id, None)
        if s is None:
            return
        for uid in list(s.buffers):
            self._flush(s, uid)
        if s.pending:
            await asyncio.gather(*list(s.pending), return_exceptions=True)
        transcript = "\n".join(s.lines)
        speakers = sorted(set(s.names.values()))
        s.lines.clear()
        if transcript.strip():
            await summarize(self.state, room_id, s.started_by, transcript, speakers, s.vocabulary)


async def summarize(state, room_id: uuid.UUID, started_by: str, transcript: str, speakers: list[str] | None = None,
                    vocabulary: list[str] | None = None) -> None:
    from .. import policy
    from ..agents.runner import _finish, _start_run, actor_for, env_for, loop, system_prompt
    from ..llm.base import ProviderError
    from ..llm.context import ContextBuilder
    from ..models import Organization, Room
    from ..services.messages import post_message

    cfg = state.agent_with_role("notes")
    if cfg is None:
        return
    async with state.db.sessions() as session:
        room = await session.get(Room, room_id)
        if room is None or room.channel_id is None:
            return
        org = (await session.execute(select(Organization).limit(1))).scalar_one()
        actor = actor_for(state, cfg, org, {room.channel_id})
        channel = await policy.get_channel(session, actor, room.channel_id)
        run = await _start_run(session, actor, channel.id, "notes", room.id, None)
        builder = ContextBuilder(session, actor, "notes").system(system_prompt(cfg, org))
        if speakers:
            builder.add_text("People who spoke:", ", ".join(speakers))
        if vocabulary:
            builder.add_text("Colleagues (for spelling names):", ", ".join(vocabulary))
        builder.add_text(f"Transcript from the room {room.name}:", transcript)
        ctx = builder.build()
        env = env_for(state, session, actor, channel, org, builder.labels, run.id)
        try:
            text = await loop(state, ctx, cfg, env, run.id, org.llm_provider)
        except ProviderError as e:
            await _finish(session, run, "failed", str(e))
            text = ""
        if not text:
            return
        await post_message(state, session, actor, channel, f"Notes from {room.name}, switched on by {started_by}\n\n{text}")
        await _finish(session, run, "done")
