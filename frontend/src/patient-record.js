// The patient detail screen's two pieces of shaping, as a plain module rather
// than part of the component.
//
// Same reason `week.js` is its own file: this repository has no `.vue` component
// test, so anything worth asserting has to live outside the component to be
// runnable under `node --test`. Neither function below talks to the API — they
// take what `GET /api/patients/{patient_no}` already returned and decide what the
// banner and the timeline say.

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

/** "18 Jun 2015" from the contract's date-only `onset_date`. */
export function onsetLabel(iso) {
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
    onsetLabel: entry.onset_date ? onsetLabel(entry.onset_date) : 'Date unknown',
    undated: !entry.onset_date,
  }))
}
