// The patient screens' shaping, as a plain module rather than part of the
// components.
//
// Same reason `week.js` is its own file: this repository has no `.vue` component
// test, so anything worth asserting has to live outside the component to be
// runnable under `node --test`. None of the functions below talks to the API --
// they take what `GET /api/patients/{patient_no}` and the directory's list
// response already returned and decide what the banner, the timeline and the
// identity line say.

// Spelled out rather than read from `toLocaleDateString`, for the reason
// `week.js` gives: a date-only string is parsed as UTC midnight, so east of
// Greenwich it renders a day early and west of it a day late. The month is looked
// up by hand instead of handed to the browser's ICU data, which makes the label
// the same everywhere and the unit test meaningful.
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/**
 * How loud the allergy banner should be, as a `data-severity` tier.
 *
 * `alert` is the design system's one reserved red — "red means allergy, nothing
 * else is red" (`style.css`) — and it is spent on a **severe** record, matching
 * the directory's red badge so the list and the detail page agree. A patient with
 * only mild or moderate records gets `warn`; `info` means the service returned no
 * allergy rows at all.
 *
 * The severity comes from the rows rather than from `has_severe_allergy`, because
 * the banner has three states and that flag has two. Both are the server's answer
 * about the same rows in the same response, so they cannot disagree.
 */
export function allergySeverity(allergies) {
  const rows = allergies ?? []
  if (rows.some((row) => row.severity === 'severe')) return 'alert'
  return rows.length ? 'warn' : 'info'
}

/**
 * "18 Jun 2015" from a date-only field: `onset_date`, `admitted_at`.
 *
 * One formatter for both, so a record cannot show an onset date in words and an
 * admission date as `2026-01-05` two lines apart.
 */
export function dateLabel(iso) {
  const [year, month, day] = String(iso).slice(0, 10).split('-')
  const name = MONTHS[Number(month) - 1]
  // A malformed value is shown as it arrived rather than as "undefined Jan NaN":
  // a wrong date on screen is bad, an unreadable one is worse.
  if (!name || !day) return String(iso)
  return `${Number(day)} ${name} ${year}`
}

/**
 * The timeline rows, in the order the server sent them.
 *
 * Deliberately **not** re-sorted. `GET /api/patients/{patient_no}/histories` and
 * the `histories` embedded in the detail response come from one reader that puts
 * the newest onset first and the undated entries last; sorting again here would be
 * a second opinion about the same rule, and the two would only have to disagree
 * once. What this adds is the display fields the view should not compute inline:
 * the formatted date, and whether there was a date to format.
 */
export function timelineOf(histories) {
  return (histories ?? []).map((entry) => ({
    // The record is carried through rather than copied field by field, so the
    // editor's "Edit" reads the same object the row rendered and `onset_date`
    // stays available for the picker to bind to.
    ...entry,
    notes: entry.notes ?? '',
    onsetLabel: entry.onset_date ? dateLabel(entry.onset_date) : 'Date unknown',
    undated: !entry.onset_date,
  }))
}

// Identity ------------------------------------------------------------------

/**
 * "Male" / "Female" / "Unknown" from the contract's `gender` enum.
 *
 * The third value is real rather than a guard: the directory offers it as a
 * filter and the service accepts it on write, so a record created without a sex
 * reads as Unknown instead of as a blank the reader has to interpret.
 */
export function genderLabel(gender) {
  return { male: 'Male', female: 'Female' }[gender] ?? 'Unknown'
}

/**
 * Whole years from the date-only `birth_date`, or `null` when the record carries
 * no usable date.
 *
 * Derived rather than stored: an age written into the row is wrong the day after
 * it is written. Read in UTC for the reason the labels above are built by hand —
 * a date-only string is UTC midnight, so a reader west of Greenwich would be a
 * day younger than the record says for part of every day.
 *
 * `now` is a parameter with a default rather than a `new Date()` inside, because
 * "has this birthday happened yet this year" is exactly the rule worth a test and
 * a test that reads the wall clock fails on the patient's birthday.
 */
export function ageFrom(birthDate, now = new Date()) {
  if (!birthDate) return null
  const born = new Date(`${birthDate}T00:00:00Z`)
  if (Number.isNaN(born.getTime())) return null
  let age = now.getUTCFullYear() - born.getUTCFullYear()
  const month = now.getUTCMonth() - born.getUTCMonth()
  if (month < 0 || (month === 0 && now.getUTCDate() < born.getUTCDate())) age -= 1
  return age
}

/**
 * The identity line both patient screens print: "Male · 62".
 *
 * The directory's Sex · Age cell and the detail page's head ask the same question
 * about the same patient, so they get the same string from one rule. A patient
 * with no birth date on record shows their sex alone rather than "Male · null".
 * `now` is `ageFrom`'s, passed through so the rule can be asserted at a fixed
 * instant.
 */
export function sexAge(patient, now = new Date()) {
  const sex = genderLabel(patient?.gender)
  const age = ageFrom(patient?.birth_date, now)
  return age === null ? sex : `${sex} · ${age}`
}
