<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
const props = withDefaults(defineProps<{ loading:boolean; empty:boolean; layout?:'cards' | 'table' }>(), { layout:'table' })
const visible = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
watch(() => props.loading && props.empty, active => {
  clearTimeout(timer); visible.value = false
  if (active) timer = setTimeout(() => { visible.value = true }, 150)
}, { immediate:true })
onBeforeUnmount(() => clearTimeout(timer))
</script>
<template><div v-if="visible" class="page-loading" :class="layout" role="status" aria-label="正在读取页面" data-page-placeholder><div v-for="index in layout === 'cards' ? 3 : 4" :key="index" aria-hidden="true"><i /><span><i /><i /></span><i /></div></div></template>
<style scoped>
.page-loading{display:grid;gap:12px;margin:20px 0 28px;min-width:0}.page-loading>div{display:flex;align-items:center;gap:20px;padding:24px;border:1px solid var(--rf-line);border-radius:10px;background:var(--rf-surface);min-height:88px;box-sizing:border-box}.page-loading i{display:block;height:14px;border-radius:5px;background:var(--rf-subtle,#edf0e8);animation:page-loading-pulse 1.2s ease-in-out infinite alternate}.page-loading>div>i:first-child{width:42px;height:42px;flex:none;border-radius:8px}.page-loading span{flex:1;min-width:0}.page-loading span>i{width:65%}.page-loading span>i+i{width:40%;height:10px;margin-top:12px}.page-loading>div>i:last-child{width:54px;flex:none}.page-loading.cards{grid-template-columns:repeat(3,minmax(0,1fr))}.page-loading.cards>div{min-height:144px;flex-wrap:wrap}.page-loading.cards>div>i:last-child{display:none}@keyframes page-loading-pulse{from{opacity:.45}to{opacity:1}}@media(max-width:850px){.page-loading.cards{grid-template-columns:1fr}.page-loading.cards>div{min-height:88px}}@media(prefers-reduced-motion:reduce){.page-loading i{animation:none}}
</style>
