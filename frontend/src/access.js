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

// Absent means "everyone signed in", which is why this is not `roles.includes`
// with a default of `[]` — that would hide every ungated screen from everyone.
export function canOpen(roles, title) {
  return !roles || roles.includes(title)
}
