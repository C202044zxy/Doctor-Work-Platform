// M5. The consultation screens draw a person the same way wherever one appears:
// an initials badge beside a name, in the participants rail, under a report
// opinion, and in the patient's consultation record. Three copies of a one-line
// rule drift apart; one exported rule cannot.
export function initials(name) {
  return (name || '')
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}
