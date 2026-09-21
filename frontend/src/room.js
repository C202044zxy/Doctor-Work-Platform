// The room M3's patient consultation and M5's remote consultation share.
//
// `docs/api/API-索引.md` pins chat and signaling to one route, `/ws/chat/{room_id}`, and
// requires a consultation and a meeting to reuse it rather than each opening a
// conversation of its own. A bare id cannot do that: `meetings.id` is a sequence of its
// own, so the fifth meeting and the fifth consultation are both 5 and the socket could
// not tell which one was meant. The key is therefore a string -- digits for a
// consultation, `m<id>` for a meeting -- which is the spelling `backend/app/rooms.py`
// already answers to. Both screens build it here, so the spelling is written down once on
// this side of the wire as well.
//
// The key is the part that has to agree. The history reads stay on their own routes,
// because their subject is a consultation or a meeting and their authorization is each
// module's own decision; `roomPaths` is where the two are spelled.

export const CONSULTATION = 'consultation'
export const MEETING = 'meeting'

// The status at which a room accepts messages and calls. `waiting` and
// `requested`/`accepted` are read-only, and `ended`/`completed` are read-only again.
// `backend/app/rooms.py` calls this the room's ready status; the strings live here
// because a second copy would be a second answer to "may I type here".
const READY = { [CONSULTATION]: 'active', [MEETING]: 'in_progress' }

export function roomKey(kind, id) {
  return kind === MEETING ? `m${id}` : String(id)
}

export function roomPaths(kind, id) {
  const base = kind === MEETING ? `/meetings/${id}` : `/consultations/${id}`
  return { messages: `${base}/messages`, calls: `${base}/calls` }
}

export function roomWritable(kind, status) {
  return status === READY[kind]
}

// Why the composer is disabled, said differently by each room. The consultation line is
// M3's own copy, word for word -- the M3 browser check asserts on it. A meeting that has
// not started is not closed, it is waiting for the initiator, and calling that read-only
// reads as a fault rather than as "not yet".
const MEETING_NOTICE = {
  completed: 'This consultation is completed, so the room is read-only.',
  declined: 'This consultation was declined, so the room never opened.',
}

export function roomNotice(kind, status) {
  if (kind !== MEETING) return 'This conversation is read-only.'
  return MEETING_NOTICE[status] ?? 'The room opens for writing when the initiator starts the consultation.'
}

// The room's state in the room's own words, for the mark above the conversation.
const MEETING_STATE = {
  requested: 'Waiting to start',
  accepted: 'Ready to start',
  in_progress: 'Live',
  completed: 'Closed',
  declined: 'Closed',
}

export function meetingState(status) {
  return MEETING_STATE[status] ?? status ?? ''
}

// Who is in a meeting: its initiator plus every expert it invited. `backend/app/meetings.py`
// answers "who is in this meeting" this way for materials and reports, and a decline closes
// the invitation rather than the record, so a declined expert is still a participant here.
// A colleague who was never invited is not, which is the 403 the socket answers with.
export function meetingParticipant(meeting, me) {
  if (!meeting) return false
  if (meeting.initiator_id === me) return true
  return (meeting.participants ?? []).some(person => person.user_id === me)
}

// A `status` frame, from either kind. M3 publishes the whole consultation row; M5
// publishes the room's own status and readiness. Both carry `status`, and a frame without
// one is not a frame this component can use -- so it is dropped rather than read as
// "unchanged", which would keep a composer the server has already refused.
export function liveFrame(frame) {
  if (!frame || typeof frame.status !== 'string') return null
  return { status: frame.status, roomKey: frame.room_key ?? null, kind: frame.kind ?? null }
}

// A confirmation drops exactly the optimistic rows whose `client_id` came back. Rows
// without one are other people's messages, and every pending row has one.
export function confirmPending(pending, rows) {
  const confirmed = new Set(rows.map(row => row.client_id).filter(Boolean))
  return pending.filter(row => !confirmed.has(row.client_id))
}

// The write body, shared by the socket and its HTTP fallback, so a resend cannot differ
// from the first attempt in anything but where it went.
export function messageBody(row) {
  return { content: row.content || '', image_url: row.image_url ?? null, client_id: row.client_id }
}

// The refusals the picker makes locally. They repeat the server's own limits so a 6 MB
// photo is not uploaded to be told so, and they read the same either way.
export function imageProblem(file) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    return 'Choose a JPEG, PNG, or WebP image'
  }
  if (file.size > 5 * 1024 * 1024) return 'Image exceeds the 5MB limit'
  return ''
}
