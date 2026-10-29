export interface Author { kind: 'user' | 'guest' | 'agent'; id: string | null; name: string; initials: string; tone: string; label: string }
export interface Attachment { id: string; filename: string; mime: string; size: number; summary: string; url: string }
export interface PullInfo { original_id: string; copy_id: string; by_id: string | null; by_name: string; at: string }
export interface WorkResult {
  id: string; channel_id: string; message_id: string | null; kind: 'quote' | 'payment_terms' | string; title: string
  data: any; sources: string[]; status: 'internal' | 'with_user' | 'sent'; staged_by_id: string | null; staged_by_name: string
  sent_at: string | null; permission: string
}
export interface Message {
  id: string; channel_id: string; author: Author; body: string; created_at: string; edited_at: string | null; attachments: Attachment[]
  pulled: PullInfo | null; pulled_from: PullInfo | null; from_draft: boolean; memory_marks: { id: string; kind: string }[]
  work_results: WorkResult[]
}
export interface Member { kind: 'user' | 'guest'; id: string; name: string; initials: string; tone: string; label: string }
export interface GuestInfo { id: string; name: string | null; company: string; expires_at: string; revoked_at: string | null; created_at: string; joined: boolean; notify: boolean }
export interface Channel {
  id: string; kind: 'internal' | 'backroom' | 'shared'; name: string; description: string; partner_name: string
  backroom_id: string | null; backroom_for_id: string | null; unread: number; members: Member[]; guests: GuestInfo[]; room_name: string
}
export interface Me {
  id: string; name: string; initials: string; tone: string; email: string; role_label: string; is_admin: boolean; org_name: string
  server_location: string; locale: string; language: string; org_language: string; notify_email: boolean
}
export interface Draft { id: string; channel_id: string; work_result_id: string | null; agent_name: string; body: string; status: string; attachments: Attachment[]; created_at: string }
export interface MemoryEntry {
  id: string; channel_id: string; kind: 'decided' | 'open' | 'committed'; text: string; owner_name: string; due_label: string
  due_date: string | null; source_message_id: string | null; source_label: string; status: 'active' | 'done'; done_at: string | null; done_note: string; created_at: string
}
export interface Agent {
  id: string; slug: string; handle: string; name: string; initial: string; description: string; role: string
  busy: boolean; drafts_waiting: number; results_waiting: number; notes_rooms: string[]
}
export interface Room {
  id: string; name: string; kind: 'normal' | 'quiet' | 'hallway'; floor_id: string; col: number; row: number; col_span: number; row_span: number
  channel_id: string | null; channel_name: string; members_only: boolean; can_enter: boolean
}
export interface Floor { id: string; name: string; columns: number }
export interface RoomsPlan { floors: Floor[]; rooms: Room[] }
export interface Person { id: string; name: string; initials: string; tone: string; role_label: string }
export interface PresenceRoom { id: string; people: { user_id: string; muted: boolean }[]; notes_by_id: string | null; notes_by_name: string }
export interface AskAnswer { question: string; answer: string; known: boolean; sources: { kind: string; id: string; channel_id: string; label: string }[] }
