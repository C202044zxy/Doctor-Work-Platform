// Fabricated content for the interface review. None of it comes from the API.
// Keeping every invented value in one file makes the mock boundary obvious and
// the deletions trivial as each module lands:
//
//   worklist, schedule, counts   -> M2 history, M4 queue, M6 thresholds, M8 panel
//   allergens                    -> M2 allergy table
//   record, versions, formulary  -> M4 records, M4 medical orders
//   consult*                     -> M3 consultation workbench
//   meeting                      -> M5 remote consultation
//   vitals, carePlan, ...        -> M6 health management
//   review*                      -> M4 chief-physician review
//   auditRows                    -> M8 audit search and export
//
// Clinical values use the units Chinese hospitals report in: mmHg for blood
// pressure, mmol/L for glucose, bpm for heart rate, g and MU for drug doses.
//
// Only the patient directory reads real data today (see views/PatientListView).

export const worklist = [
  {
    id: 'wl-1',
    severity: 'alert',
    patient: 'Zhang Wei',
    patientId: 1,
    detail: 'Allergy on file: penicillin, cephalosporins',
    action: 'Order entry blocked until reviewed',
  },
  {
    id: 'wl-2',
    severity: 'alert',
    patient: 'Liu Yang',
    patientId: 2,
    detail: 'Blood pressure 168/104 mmHg, above range for three readings',
    action: 'Review the care plan',
  },
  {
    id: 'wl-3',
    severity: 'warn',
    patient: 'Chen Jing',
    patientId: 3,
    detail: 'Admission record v2 submitted for review',
    action: 'Approve or return with a comment',
  },
  {
    id: 'wl-4',
    severity: 'warn',
    patient: 'Wu Min',
    patientId: 4,
    detail: 'Follow-up consultation request received 40 minutes ago',
    action: 'Accept and open a session',
  },
  {
    id: 'wl-5',
    severity: 'info',
    patient: 'Zhao Lei',
    patientId: 5,
    detail: 'Preventive care reminder due today',
    action: 'Confirm the reminder',
  },
]

export const schedule = [
  { time: '09:30', patient: 'Zhang Wei', kind: 'Follow-up consultation' },
  { time: '11:00', patient: 'Liu Yang', kind: 'Vital-sign review' },
  { time: '14:00', patient: 'Chen Jing', kind: 'Record review' },
  { time: '16:30', patient: 'Sun Qi', kind: 'Remote consultation' },
]

export const counts = {
  consultations: 3,
  pendingReviews: 2,
  alerts: 2,
  myPatients: 28,
}

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
// M3 - online consultation
// ---------------------------------------------------------------------------

export const consultSessions = [
  {
    id: 1,
    patient: 'Wu Min',
    patientId: 4,
    state: 'waiting',
    topic: 'Recurrent migraine — follow-up',
    preview: 'The tablets helped for about a week, then the headaches came back.',
    lastAt: '10:42',
    unread: 2,
  },
  {
    id: 2,
    patient: 'Liu Yang',
    patientId: 2,
    state: 'active',
    topic: 'Blood pressure review',
    preview: 'I have the readings from the last two weeks ready.',
    lastAt: '10:31',
    unread: 0,
  },
  {
    id: 3,
    patient: 'Sun Qi',
    patientId: 6,
    state: 'ended',
    topic: 'Inhaler technique',
    preview: 'Thank you, that is much clearer now.',
    lastAt: 'Yesterday',
    unread: 0,
  },
  {
    id: 4,
    patient: 'Li Na',
    patientId: 7,
    state: 'ended',
    topic: 'Iron tablets and stomach upset',
    preview: 'I will try taking them with food.',
    lastAt: '8 September',
    unread: 0,
  },
]

export const consultMessages = {
  2: [
    { id: 'm1', kind: 'system', text: 'Session started', at: '10:02' },
    {
      id: 'm2',
      from: 'patient',
      text: 'Good morning doctor. I have the readings from the last two weeks ready.',
      at: '10:04',
    },
    {
      id: 'm3',
      from: 'doctor',
      text: 'Good morning. Please read them out, and tell me whether you took each one at the same time of day.',
      at: '10:06',
    },
    {
      id: 'm4',
      from: 'patient',
      kind: 'image',
      file: 'home-readings.jpg',
      size: '1.4 MB',
      caption: 'My notebook from the last two weeks',
      at: '10:09',
    },
    {
      id: 'm5',
      from: 'doctor',
      text: 'Thank you, that is legible. The trend is improving. Let us keep the same dose and review again in four weeks.',
      at: '10:14',
    },
    {
      id: 'm6',
      from: 'patient',
      text: 'Understood. Should I keep taking it in the morning?',
      at: '10:31',
    },
  ],
  1: [
    { id: 'n1', kind: 'system', text: 'Waiting for a clinician to accept', at: '10:30' },
    {
      id: 'n2',
      from: 'patient',
      text: 'The tablets helped for about a week, then the headaches came back.',
      at: '10:40',
    },
    { id: 'n3', from: 'patient', text: 'They are worse in the morning now.', at: '10:42' },
  ],
  3: [
    { id: 's1', kind: 'system', text: 'Session started', at: '14:02' },
    {
      id: 's2',
      from: 'doctor',
      text: 'Show me how you hold the inhaler, as if I were in the room with you.',
      at: '14:04',
    },
    {
      id: 's3',
      from: 'patient',
      kind: 'image',
      file: 'inhaler-technique.jpg',
      size: '980 KB',
      caption: 'How I hold it',
      at: '14:07',
    },
    {
      id: 's4',
      from: 'doctor',
      text: 'Your thumb is blocking the vent. Move it to the side and shake before each puff.',
      at: '14:09',
    },
    { id: 's5', from: 'patient', text: 'Thank you, that is much clearer now.', at: '14:12' },
    { id: 's6', kind: 'system', text: 'Session ended by Dr. Chen', at: '14:15' },
  ],
  4: [
    { id: 't1', kind: 'system', text: 'Session started', at: '09:40' },
    {
      id: 't2',
      from: 'patient',
      text: 'The iron tablets are giving me stomach pain in the mornings.',
      at: '09:42',
    },
    {
      id: 't3',
      from: 'doctor',
      text: 'Take them with food rather than on an empty stomach. If the pain persists, we will switch to a different preparation.',
      at: '09:45',
    },
    { id: 't4', from: 'patient', text: 'I will try taking them with food.', at: '09:47' },
    { id: 't5', kind: 'system', text: 'Session ended by Dr. Chen', at: '09:50' },
  ],
}

export const consultPatient = {
  id: 2,
  name: 'Liu Yang',
  age: 54,
  sex: 'Female',
  department: 'Cardiology',
  problem: 'Type 2 diabetes with raised blood pressure',
  medication: ['Metformin 500 mg twice daily', 'Amlodipine 5 mg once daily'],
  lastReading: '138/86 mmHg',
  lastReadingAt: '8 September 2026',
}

// ---------------------------------------------------------------------------
// M5 - remote consultation
// ---------------------------------------------------------------------------

export const meeting = {
  id: 'RC-2026-0031',
  patient: 'Zhao Lei',
  patientId: 5,
  age: 61,
  sex: 'Male',
  topic: 'Anticoagulation after myocardial infarction',
  requestedBy: 'Dr. Chen',
  openedAt: '09:15',
  // The state machine the module implements. `at` is absent on states the
  // consultation has not reached.
  states: [
    { key: 'requested', label: 'Requested', at: '08:40' },
    { key: 'confirmed', label: 'Confirmed', at: '08:52' },
    { key: 'in_progress', label: 'In progress', at: '09:15' },
    { key: 'report', label: 'Report' },
    { key: 'archived', label: 'Archived' },
  ],
  // expiresInSeconds drives the live countdown. It is the time-limited access
  // grant that M5 issues and revokes; when it reaches zero the row locks.
  participants: [
    {
      name: 'Dr. Chen',
      department: 'Cardiology',
      role: 'Requesting clinician',
      initials: 'DC',
      expiresInSeconds: null,
    },
    {
      name: 'Dr. Lin',
      department: 'Neurology',
      role: 'Invited specialist',
      initials: 'DL',
      expiresInSeconds: 2530,
    },
    {
      name: 'Dr. Guo',
      department: 'Hematology',
      role: 'Invited specialist',
      initials: 'DG',
      expiresInSeconds: 215,
    },
  ],
  materials: [
    {
      id: 'mat-1',
      name: 'Coronary angiogram report',
      kind: 'PDF',
      size: '820 KB',
      sharedBy: 'Dr. Chen',
      at: '09:17',
    },
    {
      id: 'mat-2',
      name: 'Discharge summary, August admission',
      kind: 'PDF',
      size: '310 KB',
      sharedBy: 'Dr. Chen',
      at: '09:17',
    },
    {
      id: 'mat-3',
      name: 'Coagulation panel, 9 September',
      kind: 'PDF',
      size: '145 KB',
      sharedBy: 'Dr. Guo',
      at: '09:22',
    },
    {
      id: 'mat-4',
      name: 'Twelve-lead ECG strip',
      kind: 'PNG',
      size: '2.1 MB',
      sharedBy: 'Dr. Chen',
      at: '09:18',
    },
  ],
  opinions: [
    {
      id: 'op-1',
      author: 'Dr. Guo',
      department: 'Hematology',
      at: '09:26',
      text: 'Renal function is stable and the platelet count is normal. A direct oral anticoagulant is reasonable. I would avoid a loading dose given the bleeding history.',
    },
    {
      id: 'op-2',
      author: 'Dr. Lin',
      department: 'Neurology',
      at: '09:31',
      text: 'No prior stroke or transient ischaemic attack. Agree with anticoagulation; no neurological contraindication.',
    },
  ],
}

// ---------------------------------------------------------------------------
// M6 - patient health management
// ---------------------------------------------------------------------------

// Readings run late August to 10 September. Blood pressure and glucose start
// above their reference range and settle after treatment; the single raised
// heart rate is a one-off episode rather than a trend.
export const vitalMetrics = [
  {
    key: 'bp',
    label: 'Blood pressure',
    unit: 'mmHg',
    // Two lines share one axis, so both threshold pairs are drawn.
    series: [
      {
        name: 'Systolic',
        high: 139,
        points: [152, 148, 155, 146, 141, 144, 138, 139, 142, 135, 137, 134],
      },
      {
        name: 'Diastolic',
        high: 89,
        points: [96, 94, 98, 92, 90, 91, 88, 87, 90, 86, 85, 84],
      },
    ],
  },
  {
    key: 'glucose',
    label: 'Blood glucose',
    unit: 'mmol/L',
    series: [
      {
        name: 'Fasting glucose',
        high: 6.1,
        low: 3.9,
        points: [7.8, 7.4, 7.1, 6.9, 7.2, 6.6, 6.4, 6.1, 6.3, 5.9, 5.7, 5.6],
      },
    ],
  },
  {
    key: 'heartRate',
    label: 'Heart rate',
    unit: 'bpm',
    series: [
      {
        name: 'Resting heart rate',
        high: 100,
        low: 60,
        points: [88, 84, 79, 76, 104, 74, 71, 69, 73, 68, 66, 70],
      },
    ],
  },
]

export const vitalDates = [
  '28 Aug',
  '29 Aug',
  '31 Aug',
  '1 Sep',
  '2 Sep',
  '4 Sep',
  '5 Sep',
  '6 Sep',
  '7 Sep',
  '8 Sep',
  '9 Sep',
  '10 Sep',
]

export const carePlan = {
  title: 'Hypertension management plan',
  startedOn: '28 August 2026',
  owner: 'Dr. Chen',
  items: [
    { text: 'Amlodipine 5 mg once daily', done: true },
    { text: 'Home blood pressure readings twice weekly', done: true },
    { text: 'Reduce dietary sodium below 5 g per day', done: false },
    { text: 'Repeat lipid panel in three months', done: false },
  ],
}

export const reminders = [
  {
    id: 'rem-1',
    text: 'Take the morning blood pressure reading',
    when: 'Daily at 08:00',
    state: 'due',
  },
  {
    id: 'rem-2',
    text: 'Cardiology clinic visit',
    when: '18 September 2026, 09:30',
    state: 'scheduled',
  },
  {
    id: 'rem-3',
    text: 'Repeat lipid panel',
    when: 'Due 1 December 2026',
    state: 'scheduled',
  },
]

export const assessments = [
  {
    id: 'as-1',
    date: '10 September 2026',
    author: 'Dr. Chen',
    verdict: 'Controlled',
    severity: 'ok',
    summary:
      'Twelve readings reviewed. Both systolic and diastolic values have fallen into range over six weeks. No adverse effects reported.',
  },
  {
    id: 'as-2',
    date: '27 August 2026',
    author: 'Dr. Chen',
    verdict: 'Above target',
    severity: 'warn',
    summary:
      'Baseline assessment before treatment. Average 151/96 mmHg across four readings. Started on amlodipine 5 mg once daily.',
  },
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
