// The dashboard's week view, as a plain module rather than part of the component.
//
// Same reason `api/csv.js` is its own file: the two things that go wrong here are
// week boundaries and the UTC-to-local step, and neither is visible by looking at
// a rendered page — they are wrong for a few hours a week, or for everyone east of
// Greenwich. Keeping the arithmetic out of the `.vue` file makes it runnable under
// `node --test`, which is the only test harness this repository has.
//
// Nothing here talks to the API. It takes the `scheduled_at` strings the meetings
// endpoint already returns and decides which of the reader's days they land on.

const DAY_MS = 24 * 60 * 60 * 1000

// Spelled out rather than read from `toLocaleDateString`. `en-GB` is the locale
// the audit screen and the care-plan rows are pinned to, but even a pinned locale
// is the browser's ICU data, and the labels below are the only text in a week row
// that is not a number or a name. Fixed arrays mean the same week renders the same
// way in every browser, which is also what makes the unit test meaningful.
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

export function startOfWeek(at = new Date()) {
  const start = new Date(at)
  start.setHours(0, 0, 0, 0)
  // getDay() counts from Sunday; this shifts it to a Monday-first index, which is
  // why Sunday (0) needs the +6 rather than nothing.
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  return start
}

export function weekBounds(at = new Date()) {
  const start = startOfWeek(at)
  // Half-open: [start, end). A consultation at exactly next Monday 00:00 belongs
  // to next week, and an inclusive end would show it in both.
  return { start, end: new Date(start.getTime() + 7 * DAY_MS) }
}

export function sameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

export function isToday(at, now = new Date()) {
  return sameDay(at, now)
}

// "Mon 22 Sep". Built from the arrays above rather than from a formatter, so the
// reader's locale cannot change the wording mid-column.
export function dayLabel(at) {
  return `${WEEKDAYS[(at.getDay() + 6) % 7]} ${at.getDate()} ${MONTHS[at.getMonth()]}`
}

// The clock time in the reader's zone. `scheduled_at` arrives as a UTC instant;
// printing it raw would put an 09:30 consultation at 01:30 for anyone east of it.
export function clockTime(iso) {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const pad = (value) => String(value).padStart(2, '0')
  return `${pad(at.getHours())}:${pad(at.getMinutes())}`
}

/**
 * The week's meetings, bucketed by the reader's local day and ordered.
 *
 * Only days that carry something are returned: a seven-row grid where five rows
 * say "nothing" is five rows of noise in a rail that has other panels to hold.
 * An empty array means the whole week is free, and the caller says so once.
 */
export function weekAgenda(meetings, bounds) {
  const buckets = new Map()
  for (let index = 0; index < 7; index += 1) {
    const day = new Date(bounds.start.getTime() + index * DAY_MS)
    buckets.set(`${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`, {
      key: day.toISOString().slice(0, 10),
      day,
      label: dayLabel(day),
      items: [],
    })
  }

  for (const meeting of meetings ?? []) {
    const at = new Date(meeting?.scheduled_at)
    if (Number.isNaN(at.getTime())) continue
    if (at < bounds.start || at >= bounds.end) continue
    const bucket = buckets.get(`${at.getFullYear()}-${at.getMonth()}-${at.getDate()}`)
    if (bucket) bucket.items.push(meeting)
  }

  const days = []
  for (const bucket of buckets.values()) {
    if (!bucket.items.length) continue
    bucket.items.sort((left, right) => {
      const diff = new Date(left.scheduled_at) - new Date(right.scheduled_at)
      // Ties broken by id so two consultations at the same minute do not swap
      // places between loads.
      return diff !== 0 ? diff : (left.id ?? 0) - (right.id ?? 0)
    })
    days.push(bucket)
  }
  return days
}
