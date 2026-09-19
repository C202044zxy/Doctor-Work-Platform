// Fabricated content for the interface review. None of it comes from the API.
// Keeping every invented value in one file makes the mock boundary obvious and
// the deletions trivial as each module lands:
//
//   allergens                    -> M2 allergy table
//   record, versions, formulary  -> M4 records, M4 medical orders
//   review*                      -> M4 chief-physician review
//
// Clinical values use the units Chinese hospitals report in: mmHg for blood
// pressure, mmol/L for glucose, bpm for heart rate, g and MU for drug doses.
//
// Three blocks have left for the same reason -- their module landed -- and the
// deletions are in the history: M6's health management values (readings, plans,
// reminders, assessments now come from the API), M5's `meeting`, and the
// dashboard's `worklist` / `schedule` / `counts` (2026-09-19).
//
// That last one was the worst of them. `counts` alone fed both the dashboard and
// the shell's notification bell, so the fabricated figures were the one thing
// visible on every screen in the demo, and no page carried a marker saying so.
// The dashboard now reads the service; the bell polls the real unread-reminder
// count. Nothing here is imported by the shell any more.
//
// M3's `consult*` block is gone for the opposite reason: the module still has no
// code, and its mock workbench announced "Connected over WebSocket" on a build
// with no WebSocket route in it. Rather than carry that into the demo path, the
// Consultations screen states the gap and M3 fills it in.
//
// `auditRows` / `auditActions` below are now imported by nothing: the audit screen
// reads the API since T12. They are left in place rather than deleted here because
// M8 owns them, and their removal is M8's to make.
//
// Real data today: the patient directory (views/PatientListView), the audit log
// (views/AuditLogView), every M6 panel (components/PatientHealth), the
// remote-consultation tab of views/ConsultationsView, and the dashboard
// (views/DashboardView) with the shell around it.

// Drug classes this patient reacts to. The order check compares a prescribed
// drug's class against this list, which is how cross-reactivity is caught:
// penicillin and cephalosporin are different drugs in related classes.
export const allergens = [
  {
    substance: 'Penicillin',
    classes: ['Penicillin'],
    reaction: 'Urticaria and facial swelling',
    recorded: '12 March 2024',
    severity: 'alert',
  },
  {
    substance: 'Cephalosporins',
    classes: ['Cephalosporin'],
    reaction: 'Generalised rash on second exposure',
    recorded: '12 March 2024',
    severity: 'alert',
  },
]

// ---------------------------------------------------------------------------
// M4 - electronic medical record
// ---------------------------------------------------------------------------

export const record = {
  id: 'MR-2026-0418',
  patient: 'Zhang Wei',
  patientId: 1,
  department: 'Cardiology',
  template: 'Progress note',
  status: 'draft', // draft | submitted | archived
  author: 'Dr. Chen',
  updatedAt: '10 September 2026, 15:42',
  fields: [
    {
      label: 'Chief complaint',
      lines: 2,
      value: 'Follow-up for hypertension. Reports occasional morning headache, no chest pain.',
    },
    {
      label: 'History of present illness',
      lines: 4,
      value:
        'Diagnosed with hypertension in March 2024. Started on amlodipine 5 mg daily. Home readings have fallen from the 150s to the 130s systolic over six weeks. No syncope, no visual disturbance, no ankle swelling.',
    },
    {
      label: 'Examination',
      lines: 3,
      value:
        'Alert and comfortable at rest. Blood pressure 134/84 mmHg, heart rate 70 bpm, regular. Chest clear. No peripheral oedema. No carotid bruit.',
    },
    {
      label: 'Assessment',
      lines: 2,
      value: 'Essential hypertension, responding to treatment. No evidence of end-organ damage.',
    },
    {
      label: 'Plan',
      lines: 3,
      value: 'Continue amlodipine 5 mg. Home readings twice weekly. Review in eight weeks.',
    },
  ],
}

export const versions = [
  {
    version: 1,
    label: 'v1',
    state: 'archived',
    at: '10 September 2026, 13:05',
    author: 'Dr. Chen',
    note: 'Approved by Dr. Sun and archived. Read-only.',
  },
  {
    version: 2,
    label: 'v2',
    state: 'submitted',
    at: '10 September 2026, 14:20',
    author: 'Dr. Chen',
    note: 'Submitted for chief review. Waiting 1 h 35 m.',
  },
  {
    version: 3,
    label: 'v3',
    state: 'draft',
    at: '10 September 2026, 15:42',
    author: 'Dr. Chen',
    note: 'Draft. Editing an archived record created this linked version.',
  },
]

// Orders already written against this record, one of each verification level.
export const orders = [
  {
    id: 'ord-1',
    drug: 'Amlodipine',
    dose: '5 mg',
    route: 'PO',
    frequency: 'once daily',
    level: 'ok',
    message: 'Within the usual range.',
  },
  {
    id: 'ord-2',
    drug: 'Vancomycin',
    dose: '2 g',
    route: 'IV',
    frequency: 'every 12 hours',
    level: 'warn',
    message: 'Above the 15-20 mg/kg band for a 68 kg adult.',
    justification: 'Suspected meticillin-resistant infection; trough levels will be monitored daily.',
  },
]

// The orderable set. `typical` and `max` share the drug's own `unit`, so the
// comparison in the order dialog is a plain number against number.
export const formulary = [
  { drug: 'Amlodipine', class: 'Calcium channel blocker', route: 'PO', unit: 'mg', typical: 5, max: 10 },
  { drug: 'Furosemide', class: 'Loop diuretic', route: 'IV', unit: 'mg', typical: 40, max: 80 },
  { drug: 'Metformin', class: 'Biguanide', route: 'PO', unit: 'mg', typical: 500, max: 1000 },
  { drug: 'Ibuprofen', class: 'NSAID', route: 'PO', unit: 'mg', typical: 400, max: 400 },
  { drug: 'Amoxicillin', class: 'Penicillin', route: 'PO', unit: 'mg', typical: 500, max: 1000 },
  { drug: 'Penicillin G', class: 'Penicillin', route: 'IV', unit: 'MU', typical: 4, max: 6 },
  { drug: 'Ceftriaxone', class: 'Cephalosporin', route: 'IV', unit: 'g', typical: 2, max: 4 },
  { drug: 'Vancomycin', class: 'Glycopeptide', route: 'IV', unit: 'g', typical: 1, max: 1.5 },
]

// ---------------------------------------------------------------------------
// M4 - chief physician review queue
// ---------------------------------------------------------------------------

export const reviewQueue = [
  {
    id: 'MR-2026-0417',
    patient: 'Chen Jing',
    patientId: 3,
    author: 'Dr. Wang',
    template: 'Admission note',
    version: 2,
    submittedAt: '09:20',
    waiting: '1 h 35 m',
    severity: 'warn',
  },
  {
    id: 'MR-2026-0412',
    patient: 'Liu Yang',
    patientId: 2,
    author: 'Dr. Ma',
    template: 'Progress note',
    version: 1,
    submittedAt: '10:48',
    waiting: '7 m',
    severity: 'info',
  },
]

export const archivedRecords = [
  {
    id: 'MR-2026-0409',
    patient: 'Zhang Wei',
    patientId: 1,
    template: 'Progress note',
    version: 1,
    archivedAt: '10 September 2026, 13:05',
    approvedBy: 'Dr. Sun',
  },
  {
    id: 'MR-2026-0398',
    patient: 'Sun Qi',
    patientId: 6,
    template: 'Discharge summary',
    version: 3,
    archivedAt: '9 September 2026, 17:40',
    approvedBy: 'Dr. Sun',
  },
]

// The record currently open in the review pane, with the fields the chief
// physician is being asked to sign off and the change since the last version.
// Keyed by record id so the pane follows whatever the reviewer selects.
export const reviewDetails = {
  'MR-2026-0417': {
    id: 'MR-2026-0417',
    patient: 'Chen Jing',
    patientId: 3,
    age: 45,
    sex: 'Female',
    author: 'Dr. Wang',
    template: 'Admission note',
    version: 2,
    submittedAt: '10 September 2026, 09:20',
    // `changed` marks the fields that moved since the version below.
    fields: [
      {
        label: 'Chief complaint',
        value: 'Fever and productive cough for four days.',
        changed: true,
      },
      {
        label: 'History of present illness',
        value:
          'Four days of fever to 38.9 C with yellow sputum and right-sided pleuritic chest pain. No haemoptysis, no night sweats.',
        changed: true,
      },
      {
        label: 'Examination',
        value:
          'Temperature 38.4 C, blood pressure 122/78 mmHg, heart rate 96 bpm, oxygen saturation 94% on room air. Crackles at the right base.',
        changed: false,
      },
      {
        label: 'Assessment',
        value: 'Community-acquired pneumonia, right lower lobe. CURB-65 score 1.',
        changed: true,
      },
    ],
    orders: [
      { id: 'rv-1', drug: 'Ceftriaxone', dose: '2 g', route: 'IV', frequency: 'once daily', level: 'ok' },
      { id: 'rv-2', drug: 'Azithromycin', dose: '500 mg', route: 'PO', frequency: 'once daily', level: 'ok' },
    ],
    previous: {
      version: 1,
      author: 'Dr. Wang',
      submittedAt: '9 September 2026, 16:02',
      returnedBy: 'Dr. Sun',
      comment: 'Assessment does not state a CURB-65 score. Add it and resubmit.',
    },
  },

  'MR-2026-0412': {
    id: 'MR-2026-0412',
    patient: 'Liu Yang',
    patientId: 2,
    age: 54,
    sex: 'Female',
    author: 'Dr. Ma',
    template: 'Progress note',
    version: 1,
    submittedAt: '10 September 2026, 10:48',
    fields: [
      {
        label: 'Chief complaint',
        value: 'Routine review of blood pressure control.',
        changed: true,
      },
      {
        label: 'History of present illness',
        value:
          'Home readings over the last two weeks average 138/86 mmHg, down from the 150s. No dizziness, no headache. Tolerating amlodipine without ankle swelling.',
        changed: true,
      },
      {
        label: 'Examination',
        value:
          'Blood pressure 136/84 mmHg, heart rate 72 bpm, regular. Chest clear. No peripheral oedema.',
        changed: true,
      },
      {
        label: 'Assessment',
        value: 'Hypertension responding to treatment. Continue current dose.',
        changed: true,
      },
    ],
    orders: [
      { id: 'rv-3', drug: 'Amlodipine', dose: '5 mg', route: 'PO', frequency: 'once daily', level: 'ok' },
      { id: 'rv-4', drug: 'Metformin', dose: '500 mg', route: 'PO', frequency: 'twice daily', level: 'ok' },
    ],
    // A first submission has nothing to compare against.
    previous: null,
  },
}

// ---------------------------------------------------------------------------
// M8 - audit trail
// ---------------------------------------------------------------------------

// The planned shape: who, when, from where, on what, and the outcome. The
// audit_logs table currently stores only action, target and timestamp.
//
// `iso` backs the date-range filter, `at` is what the table displays.
export const auditRows = [
  {
    id: 1043,
    iso: '2026-09-10T15:42',
    at: '10 September 2026, 15:42',
    actor: 'dr.chen@hospital.example',
    action: 'record.submit',
    target: 'MR-2026-0418 v2',
    source: '10.20.14.31',
    outcome: 'ok',
    severity: 'info',
    detail: 'Review requested of Dr. Sun. Record locked against further edits until decided.',
  },
  {
    id: 1042,
    iso: '2026-09-10T15:38',
    at: '10 September 2026, 15:38',
    actor: 'dr.chen@hospital.example',
    action: 'order.blocked',
    target: 'Zhang Wei #1',
    source: '10.20.14.31',
    outcome: 'blocked',
    severity: 'alert',
    detail: 'Penicillin G refused: patient allergy to penicillin recorded 12 March 2024.',
  },
  {
    id: 1041,
    iso: '2026-09-10T15:30',
    at: '10 September 2026, 15:30',
    actor: 'dr.chen@hospital.example',
    action: 'patient.read',
    target: 'Zhang Wei #1',
    source: '10.20.14.31',
    outcome: 'ok',
    severity: 'info',
    detail: 'Sensitive read: allergy list and medical history.',
  },
  {
    id: 1039,
    iso: '2026-09-10T14:56',
    at: '10 September 2026, 14:56',
    actor: 'dr.guo@hospital.example',
    action: 'grant.issue',
    target: 'Zhao Lei #5',
    source: '10.20.16.7',
    outcome: 'ok',
    severity: 'warn',
    detail: 'Time-limited access for RC-2026-0031, expiring after the consultation closes.',
  },
  {
    id: 1038,
    iso: '2026-09-10T14:20',
    at: '10 September 2026, 14:20',
    actor: 'dr.chen@hospital.example',
    action: 'record.submit',
    target: 'MR-2026-0418 v2',
    source: '10.20.14.31',
    outcome: 'ok',
    severity: 'info',
    detail: 'Submitted for chief review.',
  },
  {
    id: 1035,
    iso: '2026-09-10T12:02',
    at: '10 September 2026, 12:02',
    actor: 'dr.sun@hospital.example',
    action: 'record.archive',
    target: 'MR-2026-0409 v1',
    source: '10.20.11.4',
    outcome: 'ok',
    severity: 'ok',
    detail: 'Approved and archived. Record locked to read-only.',
  },
  {
    id: 1030,
    iso: '2026-09-10T09:20',
    at: '10 September 2026, 09:20',
    actor: 'dr.chen@hospital.example',
    action: 'login',
    target: 'Session 4f2a',
    source: '10.20.14.31',
    outcome: 'ok',
    severity: 'info',
    detail: 'Two-factor sign-in completed.',
  },
  {
    id: 1028,
    iso: '2026-09-10T08:47',
    at: '10 September 2026, 08:47',
    actor: 'unknown',
    action: 'login',
    target: 'dr.ma@hospital.example',
    source: '203.0.113.44',
    outcome: 'refused',
    severity: 'alert',
    detail: 'Incorrect one-time code entered three times. Account held for five minutes.',
  },
]

export const auditActions = [
  'All actions',
  'login',
  'patient.read',
  'patient.create',
  'patient.delete',
  'record.submit',
  'record.archive',
  'order.blocked',
  'grant.issue',
]
