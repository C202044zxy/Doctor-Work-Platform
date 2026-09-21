// The room key both screens have to agree on.
//
// `/ws/chat/{room_id}` serves M3's patient consultations and M5's remote consultations
// through one route, and the two id sequences overlap. Nothing either screen renders
// would look wrong if the key were built two different ways -- the socket would simply
// answer with the other room's history -- so the spelling is asserted here instead of
// being left to two views to keep in step by eye.
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  CONSULTATION,
  MEETING,
  confirmPending,
  imageProblem,
  liveFrame,
  meetingParticipant,
  meetingState,
  messageBody,
  roomKey,
  roomNotice,
  roomPaths,
  roomWritable,
} from '../src/room.js'

test('a consultation keeps M3 digits and a meeting is prefixed', () => {
  // M3 shipped `12` in URLs, scripts and tests, so the bare form has to stay valid --
  // and the prefix is what stops `12` from also naming meeting 12.
  assert.equal(roomKey(CONSULTATION, 12), '12')
  assert.equal(roomKey(MEETING, 12), 'm12')
  assert.notEqual(roomKey(CONSULTATION, 12), roomKey(MEETING, 12))
})

test('the two history reads stay on their own routes', () => {
  assert.deepEqual(roomPaths(CONSULTATION, 12), {
    messages: '/consultations/12/messages',
    calls: '/consultations/12/calls',
  })
  assert.deepEqual(roomPaths(MEETING, 12), {
    messages: '/meetings/12/messages',
    calls: '/meetings/12/calls',
  })
})

test('a room accepts messages only in its own live status', () => {
  assert.equal(roomWritable(CONSULTATION, 'active'), true)
  assert.equal(roomWritable(CONSULTATION, 'waiting'), false)
  assert.equal(roomWritable(CONSULTATION, 'ended'), false)
  assert.equal(roomWritable(MEETING, 'in_progress'), true)
  assert.equal(roomWritable(MEETING, 'accepted'), false)
  // `completed` is the meeting's `ended`, and it is read-only in the same way.
  assert.equal(roomWritable(MEETING, 'completed'), false)
  // The two kinds do not share a status vocabulary, which is why the kind is a
  // parameter rather than something guessed from the string.
  assert.equal(roomWritable(MEETING, 'active'), false)
})

test('a meeting participants are its initiator and every invited expert', () => {
  const meeting = {
    initiator_id: 3,
    participants: [
      { user_id: 4, status: 'accepted' },
      { user_id: 5, status: 'declined' },
    ],
  }
  assert.equal(meetingParticipant(meeting, 3), true)
  assert.equal(meetingParticipant(meeting, 4), true)
  // A declined invitation closes the invitation, not the record: the expert is still a
  // participant, which is also the answer the server gives for materials and reports.
  assert.equal(meetingParticipant(meeting, 5), true)
  assert.equal(meetingParticipant(meeting, 6), false)
  assert.equal(meetingParticipant(null, 3), false)
})

test('the status frame reads the same whichever kind published it', () => {
  // M5's meeting frame, which also states readiness.
  assert.deepEqual(
    liveFrame({ room_key: 'm4', kind: 'meeting', status: 'in_progress', ready: 'in_progress', writable: true }),
    { status: 'in_progress', roomKey: 'm4', kind: 'meeting' },
  )
  // M3's consultation frame is the whole room row; these are the fields this component
  // needs out of it.
  assert.deepEqual(liveFrame({ id: 7, status: 'ended', patient_name: 'Chen Wei' }), {
    status: 'ended',
    roomKey: null,
    kind: null,
  })
  // Without a status there is nothing to apply, so the frame is dropped instead of
  // being taken as "still writable".
  assert.equal(liveFrame({ type: 'ping' }), null)
  assert.equal(liveFrame(null), null)
})

test('a confirmation drops only the rows that came back', () => {
  const pending = [
    { client_id: 'a', content: 'first' },
    { client_id: 'b', content: 'second' },
  ]
  // The socket echoes the `client_id`, so the echo removes its own optimistic row and
  // leaves the one still in flight.
  assert.deepEqual(confirmPending(pending, [{ client_id: 'a' }]), [
    { client_id: 'b', content: 'second' },
  ])
  // A row with no `client_id` is someone else's message and matches nothing.
  assert.deepEqual(confirmPending(pending, [{ id: 9, client_id: null }]), pending)
})

test('both senders carry the same body', () => {
  assert.deepEqual(messageBody({ client_id: 'a', content: 'hello', image_url: null }), {
    content: 'hello',
    image_url: null,
    client_id: 'a',
  })
  // An image-only send has no text, and the server takes the empty string for that.
  assert.deepEqual(messageBody({ client_id: 'b', image_url: '/uploads/x.png' }), {
    content: '',
    image_url: '/uploads/x.png',
    client_id: 'b',
  })
})

test('the picker refuses locally what the server would refuse anyway', () => {
  assert.equal(imageProblem({ type: 'image/png', size: 1024 }), '')
  assert.equal(imageProblem({ type: 'image/webp', size: 5 * 1024 * 1024 }), '')
  assert.match(imageProblem({ type: 'application/pdf', size: 10 }), /JPEG, PNG, or WebP/)
  assert.match(imageProblem({ type: 'image/png', size: 5 * 1024 * 1024 + 1 }), /5MB/)
})

test('a meeting that has not started is not called closed', () => {
  // The room is read-only either way, but the reason differs, and "Closed" over a
  // consultation nobody has started yet reads like a fault.
  assert.equal(meetingState('in_progress'), 'Live')
  assert.equal(meetingState('completed'), 'Closed')
  assert.equal(meetingState('requested'), 'Waiting to start')
  assert.equal(meetingState('accepted'), 'Ready to start')
  assert.equal(meetingState('declined'), 'Closed')
  // A status this build has never heard of is shown as it arrived, never dressed up
  // as one of the five above.
  assert.equal(meetingState('archived'), 'archived')
  assert.equal(meetingState(undefined), '')
})

test('each room explains its own read-only state', () => {
  // This wording is asserted by the M3 browser check, so it must not drift.
  assert.equal(roomNotice(CONSULTATION, 'ended'), 'This conversation is read-only.')
  assert.match(roomNotice(MEETING, 'requested'), /when the initiator starts/)
  assert.match(roomNotice(MEETING, 'accepted'), /when the initiator starts/)
  // Completed is the one meeting state the room never reopens from.
  assert.match(roomNotice(MEETING, 'completed'), /is completed, so the room is read-only/)
  assert.match(roomNotice(MEETING, 'declined'), /never opened/)
})
