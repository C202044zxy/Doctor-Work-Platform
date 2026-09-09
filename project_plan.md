# Doctor Work Platform — Project Plan and Schedule

## 1. Project overview

Build a demonstrable doctor workspace covering secure access, patient records, electronic medical records (EMR), online consultations, specialist consultations, health management, and audit logging.

The three main demonstration flows are:

1. Sign in with email two-factor authentication (2FA), access patients according to role and department, and inspect the audit trail.
2. Write an EMR, demonstrate allergy blocking for medical orders, and review and archive the record as read-only.
3. Conduct a text/image and video consultation, share specialist consultation materials, and review health trends and assessments.

### Delivery constraints

- Six team members; three weeks of five working days each.
- Each person works **at most four hours per day**, including meetings, reviews, corrections, and rehearsal.
- Maximum availability is **60 hours per person**, or **360 team hours**.
- Customer feedback and corrections must fit inside this allocation. Overtime is not a recovery strategy.
- Days 1–15 are relative working days. Calendar dates and course checkpoints remain to be confirmed.

### Milestones

| Deadline | Demonstrable outcome | Review |
|---|---|---|
| Day 5 | 2FA login, three-role access control, searchable patient list, audit logging | Customer review 1 |
| Day 10 | Complete patient profile and EMR workflow, including allergy blocking and archive locking | Customer review 2 |
| Day 14 | Text/image and video consultations, specialist consultations, health trends, integrated system | Customer review 3 |
| Day 15 | Final corrections, acceptance results, rehearsed presentation, packaged deliverables | Final acceptance |

## 2. Team and responsibilities

| Code | Role | Main responsibilities | Original task weight |
|---|---|---|---|
| A | Lead backend developer | Architecture, authentication, EMR core, video calls | 1.25 |
| B | Lead full-stack developer | Audit middleware, WebSocket services, EMR backend, scheduled jobs | 1.25 |
| C | Frontend developer | Patient, EMR, and health management interfaces | 1.0 |
| D | Full-stack developer | Patient, specialist consultation, and health APIs; deployment | 1.0 |
| E | Customer manager | Requirements, customer communication, acceptance testing, demo data | 0.5 |
| F | Product manager | Prototypes, design documents, demo script, presentation materials | 0.5 |

Task weights describe the original allocation approach; they do not increase anyone's available hours. The original capacity model also assumes A and B can complete 1.25 estimated task-hours per actual hour. That productivity assumption needs validation before committing to the schedule. E and F's remaining time is for communication, documentation, and acceptance work.

Assign actual names to A–F before kickoff. The original plan recommends A as team lead, with B able to take over critical EMR tasks.

## 3. Scope

All estimates below are **estimated task-hours**, not guaranteed elapsed working hours. The detailed task register in Section 5 is the source of truth.

### Required baseline

| Area | Minimum deliverable | Task-hours |
|---|---|---:|
| Infrastructure | Application scaffolding, database, configuration, one-command startup | 14 |
| M1 — Secure access | Password and email 2FA, JWT, three-role RBAC, department data scope, temporary grants | 26 |
| M2 — Patient information | Search, complete profiles, allergy warnings, manual grouping | 27 |
| M3 — Online consultations | WebSocket text/image chat, searchable/exportable records, WebRTC video calls | 30 |
| M4 — EMR | Templates, record editing and versioning, medical orders, allergy blocking, dose warnings, review and archive locking | 38 |
| M5 — Specialist consultations | Requests and acceptance, shared materials, generated reports | 12 |
| M6 — Health management | Vital signs, trend charts, health plans, reminders, periodic assessments | 22 |
| M8 — Audit logging | Instrumentation, filtering by user/time/action, CSV export | 8 |
| **Total** | | **177** |

The original scope summary listed M2 as 26 hours and the total as 176 hours. T13–T17 total **27 hours**, making the corrected feature total **177 hours**.

### Excluded features and substitutions

| Feature | Baseline decision | Rationale recorded in the original plan |
|---|---|---|
| M7 — Doctor community | Defer the entire module to a later phase | Marked “Optional” in the requirements presentation; independent of core clinical workflows |
| Automatic call recording | Store text/image history and call start/end times and duration | Avoid cloud recording service setup and cost |
| SMS verification | Use email verification | Avoid SMS service eligibility and cost constraints |
| Facial recognition | Reserve an integration point; do not implement | Live biometric verification service is outside the baseline |
| IoT vital-sign collection | Manual entry and simulated data scripts | No hardware available |
| Enterprise monitoring | Exclude from baseline; a small statistics dashboard remains optional | Full monitoring infrastructure exceeds course scope |

These substitutions must be explained during the presentation. Service pricing and eligibility statements are original planning assumptions, not independently verified facts.

### Optional backlog

Optional work has no reserved baseline capacity. Start it only after required work and feedback obligations are covered.

| Feature | Task-hours | Original trigger |
|---|---:|---|
| System statistics dashboard | 6 | Required work finishes early in Week 3 |
| M5 multi-user live chat | 8 | Required work finishes early in Week 3 |
| M4 laboratory/examination orders | 6 | Required work finishes early in Week 3 |
| M2 bulk grouping and bulk plan assignment | 6 | Explicit customer request, followed by scope/capacity review |
| Docker Compose orchestration | 4 | Needed for the deployment demonstration |

### Video call implementation and fallback

Video remains a required baseline feature because the original plan cites slide 5 as explicitly requesting high-definition video calls.

- Use native browser WebRTC for peer-to-peer calls.
- Reuse the M3 WebSocket service for signaling.
- Store call start/end times and duration.
- Plan the demonstration on the same local network or with two browser tabs on one machine.
- The baseline avoids a managed video provider account. Public-network connectivity may require TURN infrastructure; its deployment and cost are outside this baseline. Video quality and demo connectivity still need testing.

**Unresolved scope conflict:** the original risk plan also proposes dropping video if T29 is not working by the end of Day 13. That would remove a required feature. Treat this as a proposed fallback requiring an explicit scope decision, not an equivalent delivery. Text/image chat and call metadata do not satisfy a video-call requirement.

## 4. Capacity and schedule feasibility

### Actual available hours

| Group | Calculation | Available hours |
|---|---|---:|
| Developers A–D | 4 people × 15 days × 4 hours | 240 |
| Managers E–F | 2 people × 15 days × 4 hours | 120 |
| **Team** | | **360** |

### Developer budget from the original plan

| Use | Actual team hours | Notes |
|---|---:|---|
| Kickoff and setup meeting | 8 | Day 1; two hours per developer |
| Weekly check-ins and sprint reviews | 12 | Approximately one hour per developer per week |
| Customer feedback correction reserve | 18 | Three allocations of 1.5 hours per developer |
| Integration and defect fixing | 12 | Week 3 |
| API/deployment documentation support | 4 | Swagger export and manual cleanup |
| Day 15 corrections and rehearsal | 16 | Four hours per developer |
| **Remaining feature development time** | **170** | 240 minus 70 hours above |

The 18-hour correction reserve and 16-hour Day 15 allocation are separate budget lines. However, the original review schedule also assigns 1.5 hours per person to each customer review. Whether those meetings consume the correction reserve or the meeting budget is unresolved. Confirm this before treating 170 hours as usable feature time.

For E and F, the original budget reserves 24 hours for meetings/customer communication and 96 hours for documentation, prototypes, acceptance, and presentation work. Named management tasks total only 50 hours; the remaining 46 hours of that work budget are not assigned to specific tasks.

### Estimated workload versus capacity

The original model divides the 170 feature hours equally: 42.5 actual hours per developer. Applying its productivity assumptions gives A and B 53.125 estimated task-hours each, and C and D 42.5 each: **191.25 estimated task-hours** in total.

Against 177 feature task-hours, the theoretical margin is **14.25 task-hours**, approximately 7.5%. This is conditional on the productivity assumptions and excludes the unresolved budget issues above.

| Developer | Feature task-hours | Assumed estimated capacity | Difference |
|---|---:|---:|---:|
| A | 49 | 53.125 | 4.125 remaining |
| B | 48 | 53.125 | 5.125 remaining |
| C | 44 | 42.5 | **1.5 over** |
| D | 36 | 42.5 | 6.5 remaining |
| **Total** | **177** | **191.25** | **14.25 remaining** |

T17 is split equally between C and D for this calculation, as specified in its task description. A positive team total does not resolve C's overload or dependency bottlenecks.

### Scheduling issues to resolve

- **Week 2 frontend overload:** C has 20 feature task-hours before meetings or feedback. Redistribute or move work before confirming the sprint.
- **Extra polishing work:** Week 3 includes nine hours of UI polish/demo-data support that were not separately reserved in the capacity budget. Assign these to remaining capacity or reduce them explicitly.
- **Review versus correction time:** Account for both activities without double-counting the 18-hour reserve.
- **Day 15 limit:** The original four two-hour entries exceed the daily cap when everyone participates. Section 6 provides a four-hour replacement agenda.
- **Dependencies:** Validate task sequencing at daily resolution, especially Week 1 access control and Week 2 EMR work. Weekly totals alone do not prove feasibility.

## 5. Work breakdown and sprint assignments

Hours in this section are estimated task-hours. Joint ownership does not multiply an estimate. Task IDs are preserved for traceability; T27 and T29 appear in Sprint 3 because that is where they are scheduled.

### Sprint 1 — Foundation, access, audit, and patient list (Days 1–5)

Goal: users can sign in, view patients, and have relevant actions logged.

| ID | Task | Area | Hours | Owner | Depends on |
|---|---|---|---:|---|---|
| T01 | FastAPI and Vue 3 scaffolding; Git branching conventions | Infrastructure | 4 | A | — |
| T02 | MySQL schema and Alembic migrations for users, roles, departments, patients, allergies, and logs | Infrastructure | 4 | A | T01 |
| T03 | Redis integration, configuration, standard responses and exceptions | Infrastructure | 3 | B | T01 |
| T04 | One-command startup script and README | Infrastructure | 3 | D | T01 |
| T05 | User/role/department models, bcrypt, JWT issuance and validation | M1 | 5 | A | T02 |
| T06 | SMTP email verification codes with five-minute Redis expiry | M1 | 4 | B | T03 |
| T07 | Login/code pages, token storage, route guards | M1 | 5 | C | T05 |
| T08 | Three-role permission matrix and API authorization middleware | M1 | 4 | B | T05 |
| T09 | Department-based data filtering with administrator exemption | M1 | 3 | B | T08 |
| T10 | Temporary grants and automatic expiry using APScheduler | M1 | 5 | A | T08 |
| T11 | Audit middleware for writes and sensitive queries | M8 | 4 | B | T03 |
| T12 | Audit search by user/time/action and CSV export | M8 | 4 | C | T11 |
| T13 | Patient CRUD and search by name, ID, symptom tags, admission date | M2 | 6 | D | T02 |
| T14 | Allergy record management and red warning banner on patient details | M2 | 4 | D | T13 |
| T15 | Patient list with search, pagination, table; mocks before API integration | M2 | 6 | C | T13 |

**Feature subtotal: 64 hours** — A: 18, B: 18, C: 15, D: 13. The original subtotal was 66 hours; its separate weekly table moved part of T17 into Week 1 without defining a consistent split. This revision keeps all of T17 in Sprint 2 pending rebalancing.

### Sprint 2 — Complete patient records and EMR workflow (Days 6–10)

Goal: demonstrate EMR creation, order validation, review, and archiving. Start backend foundations for Week 3 features.

| ID | Task | Area | Hours | Owner | Depends on |
|---|---|---|---:|---|---|
| T16 | Patient details: basic information, history timeline, allergies, treatment plans | M2 | 5 | C | T14 |
| T17 | Create groups, add/remove patients, filter by group; equal frontend/backend split | M2 | 6 | D + C | T13 |
| T18 | Template model, two preset EMR templates, management API | M4 | 5 | A | T02 |
| T19 | EMR CRUD and versioning: draft, submission, version number | M4 | 6 | A | T18 |
| T20 | Medical order model and create/update/discontinue APIs | M4 | 5 | B | T13 |
| T21 | Order validation: red allergy-conflict block and yellow dose-range warning | M4 | 5 | A | T14, T20 |
| T22 | EMR editor: template selection, dynamic form, save draft, submit | M4 | 7 | C | T18 |
| T23 | Medical order interface and validation dialogs | M4 | 5 | C | T21 |
| T24 | Review queue, approve/archive or return, read-only archive lock | M4 | 5 | A | T19 |
| T25 | WebSocket service, consultation/message models, real-time messaging | M3 | 6 | B | T03 |
| T26 | Text/image messages with local image storage and returned URLs | M3 | 4 | B | T25 |
| T28 | Consultation records: patient/date/keyword search and CSV export | M3 | 4 | D | T25 |
| T30 | Specialist consultation model, invitations, and requested/accepted/in-progress/completed states | M5 | 4 | D | T13 |
| T33 | Vital-sign model and entry API for blood pressure, glucose, heart rate; threshold checks | M6 | 4 | D | T13 |
| T36 | APScheduler in-app reminders, dashboard indicator, reminder list | M6 | 5 | B | T03 |

**Feature subtotal: 76 hours** — A: 21, B: 20, C: 20, D: 15. The original subtotal was 74 hours. This sprint requires rebalancing before commitment.

### Sprint 3 — Consultations, health management, and integration (Days 11–14)

Goal: complete the remaining baseline workflows and prepare the integrated demonstration.

| ID | Task | Area | Hours | Owner | Depends on |
|---|---|---|---:|---|---|
| T27 | Online consultation workspace with waiting/active/ended states and chat UI | M3 | 6 | B | T26 |
| T29 | WebRTC video calls, WebSocket signaling, call metadata | M3 | 10 | A | T25 |
| T31 | Upload/share/download specialist consultation materials using local storage | M5 | 3 | D | T30 |
| T32 | Jinja2 consultation report and print page; list/detail frontend | M5 | 5 | D | T30 |
| T34 | ECharts trends with metric switching and red threshold highlights | M6 | 5 | C | T33 |
| T35 | Health plans: create/list/detail backend and frontend | M6 | 4 | B | T13 |
| T37 | Periodic assessment forms and assessment history | M6 | 4 | C | T33 |

**Feature subtotal: 37 hours** — A: 10, B: 10, C: 9, D: 8.

Additional scheduled work:

| Work | Hours | Owners | Budget treatment |
|---|---:|---|---|
| Integration and defect fixing | 12 | A, B, D | Already reserved in the developer budget; do not add twice |
| UI polishing and demo-data support | 9 | C, D | Additional workload; capacity allocation unresolved |
| **Additional subtotal** | **21** | | |

Sprint 3 therefore lists **58 hours including integration and polishing**, consistent with the original task table. The original weekly owner totals did not allocate these activities consistently, so individual shares remain to be assigned.

### Management and documentation tasks

| ID | Task | Timing | Hours | Owner | Depends on |
|---|---|---|---:|---|---|
| M01 | Final requirements specification and acceptance criteria | Sprint 1 | 8 | E | — |
| M02 | Login, patient list, and patient details wireframes | Sprint 1 | 8 | F | M01 |
| M03 | Database design document and API documentation from Swagger | Sprint 2 | 6 | F | T02 |
| M04 | Sprint 1 acceptance checks and refined EMR/consultation prototypes | Sprint 2 | 8 | E | — |
| M05 | Demo-data script v1: doctors, patients, allergies, EMRs | Sprint 2 | 4 | E + F | T13 |
| M06 | Final demo script and presentation slides | Sprint 3 | 8 | F | — |
| M07 | User acceptance testing (UAT) and defect list | Sprint 3 | 8 | E | — |
| **Total** | | | **50** | | |

M05 allocates two hours each to E and F. Meeting time is separate. The remaining management work budget must cover ongoing feedback tracking, final acceptance, packaging, rehearsal, and other work still to be assigned.

## 6. Reviews, feedback, and final-day agenda

### Working rhythm

- Hold a kickoff on Day 1, followed by Sprint 1 implementation within the daily cap.
- Hold one 30-minute check-in each Monday. There are **no daily stand-ups**.
- Each check-in covers completed work, next work, and blockers.
- Review customer feedback at the start of the next working day; include that time in the budget.
- Use FastAPI Swagger as the API contract from Week 1. Frontend work may use mocks while APIs are being built.

### Customer review windows

| Review | Timing | Planned duration per participant | Demonstration | Follow-up |
|---|---|---|---|---|
| 1 | End of Day 5 | 1.5 hours | 2FA, role differences, patient list, audit logs | Classify on Day 6; schedule Sprint 2 corrections |
| 2 | End of Day 10 | 1.5 hours | EMR workflow, allergy block, archive lock | Classify on Day 11; schedule Sprint 3 corrections |
| 3 | End of Day 14 | 1.5 hours | Text/image/video, specialist consultation, health trends | Prioritize Day 15 corrections |
| Acceptance | Day 15 | Within the four-hour agenda below | Check acceptance criteria and outstanding defects | Record final result |

Review durations must fit within the four-hour day. Their relationship to the separate correction reserve must be clarified as described in Section 4.

### Feedback handling

1. E classifies feedback as **Must fix**, **Should fix**, or **Optional** and maintains the customer feedback tracker.
2. Schedule must-fix work within remaining capacity. If it exceeds the reserve, explicitly defer equivalent lower-priority scheduled work. Removing an unscheduled optional item does not free baseline capacity.
3. Split corrections estimated above four hours into smaller tasks. If deferral is proposed, record the scope decision; splitting does not reduce total effort or remove a must-fix obligation.
4. Record the request, priority, owner, decision, and outcome for each item. Use the tracker as evidence of responding to customer feedback during the presentation.

### Day 15 — Revised four-hour agenda

This replaces the original overlapping two-hour blocks, which could require up to eight hours per person.

| Elapsed time | Activity | Participation |
|---|---|---|
| 0:00–2:00 | Priority corrections and acceptance checks in parallel; record unresolved defects | A–D fix and support checks; E leads UAT; F prepares final materials |
| 2:00–3:00 | Rehearse the three demonstration flows | All |
| 3:00–4:00 | Presentation/Q&A rehearsal, final acceptance status, deliverable packaging | All; F coordinates presentation and E records acceptance status |

This agenda reserves four hours per person; it does not guarantee that every late correction can be completed. Resolve scope and acceptance status explicitly if work remains.

## 7. Risks and response rules

| Risk | Trigger or impact | Planned response |
|---|---|---|
| Video implementation stalls | T29 is not working by the end of Day 13; A owns the ten-hour task | Escalate the required-feature scope conflict. Original fallback: stop remaining video work and use remaining capacity for integration/polish. Already spent hours cannot be recovered. |
| Feedback exceeds the reserve | Corrections exceed 18 hours or remaining available time | Reprioritize scheduled work with equal capacity removed; document any baseline scope change |
| EMR estimate is too low | The 38-hour EMR scope threatens the Day 10 milestone | Proposed simplifications: reduce two templates to one and use a static form instead of dynamic rendering; record the scope change |
| Critical work depends on A | Absence or delay blocks infrastructure, authentication, EMR, or video | B must be able to take over T21/T24; commit critical-task code each working day |
| Frontend/backend integration causes rework | Contract mismatches consume integration time | Keep Swagger authoritative and develop frontend mocks against the contract |
| Available working time drops | A member records less than three hours on two consecutive days | Reassign work and revisit capacity at the weekly check-in; do not exceed the daily cap |
| Owner or sprint overload | C's load and unresolved overhead exceed available hours | Rebalance ownership/timing before committing; protect required workflows and feedback time |

## 8. Deliverables and acceptance evidence

| Deliverable | Owner | Due |
|---|---|---|
| Runnable frontend, backend, database, and Redis system | A–D | Day 14 |
| Requirements specification and acceptance criteria | E | Day 5 |
| Database design document | F | Day 10 |
| Exported Swagger API documentation | F | Day 10 |
| Final system demo script | F | Day 14 |
| Presentation slides | F | Day 15; draft prepared in Sprint 3 |
| UAT report and defect list | E | Day 15 |
| Customer feedback tracker covering all three reviews and decisions | E | Day 15 |
| Deployment instructions and one-command startup script | D | Day 5 |
| Demo-data script | E + F | Day 10 |

Acceptance criteria are defined in M01 and checked by E. The final demonstration should cover all baseline areas listed in Section 3 and disclose exclusions and limitations. The original claim that “all nine modules except M7” would be demonstrated is not supported by the listed scope: it names seven numbered modules, M1–M6 and M8. Confirm whether the source presentation contains an additional module.

## 9. Decisions needed before schedule approval

| Decision | Why it matters |
|---|---|
| Assign names to A–F and confirm the team lead | Establish ownership and backup coverage |
| Map Days 1–15 to actual dates and course checkpoints | Align customer reviews and submission requirements |
| Confirm the course grading rubric | Prioritize documentation, demonstration, and optional work appropriately |
| Validate A/B productivity assumptions and rebalance C's tasks | Team-level capacity does not guarantee an executable schedule |
| Separate customer review time from correction time | Prevent double-counting available developer hours |
| Allocate nine hours of polishing and remaining management hours | Complete the workload budget |
| Confirm the video fallback and other scope substitutions | Ensure reduced delivery is explicitly acknowledged |
| Reconcile the stated nine modules with the listed module IDs | Avoid promising an unidentified or omitted module |

The next planning step is to resolve these decisions and produce a daily allocation that stays within four hours per person. The task register above provides a consistent baseline for that work.
