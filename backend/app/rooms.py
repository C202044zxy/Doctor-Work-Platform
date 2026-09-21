"""The one room identity that M3's patient consultation and M5's remote consultation share.

`docs/api/API-索引.md` pins chat and signaling to `/ws/chat/{room_id}` and requires
consultations and meetings to share that single route rather than each opening one of
their own. An integer room id could only ever name a consultation: `meetings.id` is a
separate sequence, so `5` is genuinely ambiguous between the two tables.

The room key is therefore a string. Bare digits still mean a consultation, so every
URL, script and test M3 shipped resolves unchanged; `m<id>` means a meeting. A key that
parses as neither is a 404 rather than a guess.

This module is the only place that knows which kind of room a key names. `chat` and
`calls` ask it for the patient, the participants and the lifecycle status, then serve
both kinds through one code path.

Authorization, deliberately: a caller who is not a participant is refused, but the code
differs by kind and each is the one its own module already answers with. A meeting is a
403: its membership rule is the invitation list and nothing else, and
`docs/api/API-索引.md` names the meeting signaling room as a 403. A consultation stays
404, because the patient scope hides the room outright before any participant check runs.
A key that names nothing is a 404 either way. One place still decides both, which is what
sharing the route buys.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import or_

from app.models import Meeting
from app.work_common import scoped
from app.work_models import Consultation

CONSULTATION = "consultation"
MEETING = "meeting"
MEETING_PREFIX = "m"


def consultation_key(consultation_id: int) -> str:
    """A consultation room, spelled in digits so M3's existing links already are one."""
    return str(consultation_id)


def meeting_key(meeting_id: int) -> str:
    return f"{MEETING_PREFIX}{meeting_id}"


def consultation_id_of(key: str) -> int | None:
    """The consultation a room key names, or None when it names a meeting."""
    return int(key) if key.isdigit() else None


def meeting_id_of(key: str) -> int | None:
    return int(key[1:]) if key[:1] == MEETING_PREFIX and key[1:].isdigit() else None


@dataclass(frozen=True)
class Room:
    """A consultation or a meeting, reduced to what a live room needs.

    `participants` is the authorization set for the socket, for sending and for
    signaling. For a consultation that is the initiating assistant plus the doctor who
    accepted; for a meeting it is the initiator plus every invitee -- the same set
    `meetings.is_participant` uses for materials and reports, so the module keeps one
    answer to "who is in this meeting" instead of two.
    """

    key: str
    kind: str
    id: int
    patient_id: int
    status: str
    participants: frozenset
    doctor_id: int | None = None
    # The ORM row the room was resolved from. The chat list and the consultation
    # preview still read it, and carrying it here saves every caller a second lookup.
    row: object | None = None

    @property
    def label(self) -> str:
        return CONSULTATION if self.kind == CONSULTATION else MEETING

    @property
    def ready(self) -> str:
        """The status a room has to reach before it accepts a message or a call."""
        return "active" if self.kind == CONSULTATION else "in_progress"

    @property
    def writable(self) -> bool:
        return self.status == self.ready

    def is_participant(self, user_id: int) -> bool:
        return user_id in self.participants

    def sender_type_for(self, user) -> str:
        """A consultation is the patient channel; a meeting is doctor to doctor."""
        if self.kind == MEETING or user.id == self.doctor_id:
            return "doctor"
        return "patient_assist"

    def data(self) -> dict:
        """The room as the WebSocket `status` event publishes it."""
        return {
            "room_key": self.key,
            "kind": self.kind,
            "id": self.id,
            "patient_id": self.patient_id,
            "status": self.status,
            "ready": self.ready,
            "writable": self.writable,
        }


def parse(key: str) -> tuple:
    """(kind, id) for a room key. Anything else is a 404, never a fallback."""
    text = (key or "").strip()
    if text.isdigit() and int(text) > 0:
        return CONSULTATION, int(text)
    if text[:1] == MEETING_PREFIX and text[1:].isdigit() and int(text[1:]) > 0:
        return MEETING, int(text[1:])
    raise HTTPException(404, "Room not found")


def consultation_scope(db):
    """The waiting queue is shared; accepted conversations belong to their participants."""
    user_id = db.info["user"].id
    return scoped(Consultation, db).where(
        or_(
            Consultation.status == "waiting",
            Consultation.created_by == user_id,
            Consultation.doctor_id == user_id,
        )
    )


def _consultation(db, consultation_id: int) -> Room:
    row = db.scalar(consultation_scope(db).where(Consultation.id == consultation_id))
    if row is None:
        raise HTTPException(404, "Consultation not found")
    return Room(
        key=consultation_key(row.id),
        kind=CONSULTATION,
        id=row.id,
        patient_id=row.patient_id,
        status=row.status,
        doctor_id=row.doctor_id,
        participants=frozenset(user_id for user_id in (row.created_by, row.doctor_id) if user_id),
        row=row,
    )


def _meeting(db, meeting_id: int) -> Room:
    # Deliberately no department filter: an invited expert from another department is
    # the premise of M5 and of the automatic temp_grant, so participant membership is
    # the whole check.
    row = db.get(Meeting, meeting_id)
    if row is None:
        raise HTTPException(404, "Meeting not found")
    return Room(
        key=meeting_key(row.id),
        kind=MEETING,
        id=row.id,
        patient_id=row.patient_id,
        status=row.status,
        participants=frozenset(
            (row.initiator_id, *(invitation.user_id for invitation in row.participants))
        ),
        row=row,
    )


def _guard(resolved: Room, db, participant: bool) -> Room:
    if participant and not resolved.is_participant(db.info["user"].id):
        raise HTTPException(403, f"Only the {resolved.label}'s participants may do this")
    return resolved


def consultation_room(db, consultation_id: int, *, participant: bool = False) -> Room:
    return _guard(_consultation(db, consultation_id), db, participant)


def meeting_room(db, meeting_id: int, *, participant: bool = False) -> Room:
    return _guard(_meeting(db, meeting_id), db, participant)


def room(db, key: str, *, participant: bool = False) -> Room:
    """Resolve a room key of either kind, optionally refusing a non-participant."""
    kind, id = parse(key)
    resolved = _consultation(db, id) if kind == CONSULTATION else _meeting(db, id)
    return _guard(resolved, db, participant)
