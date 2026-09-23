import { reactive } from 'vue'

export const FONTS = [
  { id: 'system', label: 'System default', value: '"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif' },
  { id: 'sans', label: 'Arial / Microsoft YaHei', value: 'Arial, "Microsoft YaHei", sans-serif' },
  { id: 'serif', label: 'Georgia / SimSun', value: 'Georgia, "Times New Roman", SimSun, serif' },
]
export const THEMES = [
  { id: 'teal', label: 'Teal', color: '#0f5f5c' },
  { id: 'blue', label: 'Blue', color: '#225ba0' },
  { id: 'violet', label: 'Violet', color: '#6846a5' },
  { id: 'amber', label: 'Amber', color: '#82570b' },
]
export const appearance = reactive({ font: 'system', theme: 'teal' })
export const appearanceKey = userId => `dwp.appearance.${userId}`

export function normalizeAppearance(value) {
  return {
    font: FONTS.some(font => font.id === value?.font) ? value.font : 'system',
    theme: THEMES.some(theme => theme.id === value?.theme) ? value.theme : 'teal',
  }
}
function mix(color, target, weight) {
  const channels = color.slice(1).match(/../g).map(part => parseInt(part, 16))
  return '#' + channels.map(channel => Math.round(channel * (1 - weight) + target * weight).toString(16).padStart(2, '0')).join('')
}
export function applyAppearance(value) {
  Object.assign(appearance, normalizeAppearance(value))
  const style = document.documentElement.style
  const color = THEMES.find(theme => theme.id === appearance.theme).color
  style.setProperty('--font-ui', FONTS.find(font => font.id === appearance.font).value)
  style.setProperty('--teal', color)
  style.setProperty('--teal-dark', mix(color, 0, 0.2))
  style.setProperty('--teal-soft', mix(color, 255, 0.9))
  style.setProperty('--el-color-primary', color)
  style.setProperty('--el-color-primary-dark-2', mix(color, 0, 0.2))
  for (const step of [3, 5, 7, 8, 9]) style.setProperty(`--el-color-primary-light-${step}`, mix(color, 255, step / 10))
}
export function loadAppearance(userId) {
  let saved = null
  if (userId) {
    try { saved = JSON.parse(localStorage.getItem(appearanceKey(userId))) } catch { /* Fall back to defaults for unavailable or malformed storage. */ }
  }
  applyAppearance(saved)
}
export function saveAppearance(userId, value) {
  const normalized = normalizeAppearance(value)
  // Persist before updating the preview, so a storage failure is reported honestly.
  localStorage.setItem(appearanceKey(userId), JSON.stringify(normalized))
  applyAppearance(normalized)
}
