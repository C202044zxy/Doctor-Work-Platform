import { createApp, watch } from 'vue'
import ElementPlus from 'element-plus'

// Element Plus first, then our tokens: style.css re-themes it by overriding the
// --el-* custom properties, and later declarations win at equal specificity.
import 'element-plus/dist/index.css'
import './style.css'

import App from './App.vue'
import router from './router'
import { currentUserId } from './session'
import { appearanceKey, loadAppearance } from './appearance'

watch(currentUserId, loadAppearance, { immediate: true })
window.addEventListener('storage', event => {
  if (event.key === appearanceKey(currentUserId.value) || event.key === null) loadAppearance(currentUserId.value)
})

createApp(App).use(router).use(ElementPlus).mount('#app')
