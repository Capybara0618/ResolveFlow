<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { readStorePresentation } from '../presentation-client'
import CatalogImage from './CatalogImage.vue'
import Icon from './ReviewIcon.vue'
const props = withDefaults(defineProps<{ id: string; size?: number }>(), { size: 17 })
const logo = ref<string | null>(null)
let generation = 0
watch(() => props.id, async () => { const g = ++generation; logo.value = null; try { const store = await readStorePresentation(props.id); if (g === generation) logo.value = store.logo_id } catch { /* The storefront icon remains available. */ } }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<template><span class="store-mark" :style="{ width: `${size}px`, height: `${size}px` }" aria-hidden="true"><CatalogImage v-if="logo" :id="logo" name="店铺" /><Icon v-else name="store" :size="size" /></span></template>
<style scoped>.store-mark{display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;border-radius:50%;overflow:hidden;vertical-align:middle}</style>
