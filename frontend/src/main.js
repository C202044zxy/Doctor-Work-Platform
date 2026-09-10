import { createApp } from 'vue'
import ElementPlus from 'element-plus'

// Element Plus first, then our tokens: style.css re-themes it by overriding the
// --el-* custom properties, and later declarations win at equal specificity.
import 'element-plus/dist/index.css'
import './style.css'

import App from './App.vue'
import router from './router'

createApp(App).use(router).use(ElementPlus).mount('#app')
