import './ui/tokens.css'
import { createApp } from 'vue'

const page = import.meta.env.DEV && new URLSearchParams(window.location.search).get('preview') === 'review'
  ? import('./preview/ReviewPreview.vue')
  : import('./App.vue')

page.then(({ default: App }) => createApp(App).mount('#app'))
