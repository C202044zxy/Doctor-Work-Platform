// T07 签收标准 3, in one place.
//
// The role that may open a screen has to be stated twice — once on the sidebar
// entry so a junior never sees 病历审阅 or 审计日志, and once on the route so typing
// the path in the address bar does not get around it. 场景 S1 checks both halves
// and T12's S2 refuses a build that only does the first, so the two statements
// have to come from one table rather than being typed out twice and drifting.
//
// `title` is the API's field name for the role and the contract forbids renaming
// it. The only values it takes are admin, senior and junior.
export const MODULE_ROLES = {
  review: ['senior'],
  audit: ['admin'],
}

// The service answers 403 for two different things, and only one of them is about
// the screen. `require_permission` refuses a permission the role does not carry and
// names it; every other 403 refuses one action inside a screen the caller may open
// — writing a patient into another department, answering a consultation they were
// not invited to, revising somebody else's assessment. Only the first replaces the
// page with the 403 explainer; the second has to be read on the form that asked,
// because losing the screen over it hides the sentence that says what was wrong.
const MISSING_PERMISSION = /^Missing permission:/i

export function isScreenRefusal(status, message) {
  return status === 403 && MISSING_PERMISSION.test(message ?? '')
}

// Absent means "everyone signed in", which is why this is not `roles.includes`
// with a default of `[]` — that would hide every ungated screen from everyone.
export function canOpen(roles, title) {
  return !roles || roles.includes(title)
}
