<script setup lang="ts">
withDefaults(defineProps<{ page: number; hasNext: boolean; disabled?: boolean; label?: string }>(), { label: '记录分页' })
const emit = defineEmits<{ change: [page: number] }>()
</script>
<template>
  <nav class="list-pagination" :aria-label="label">
    <button type="button" :disabled="disabled || page === 0" @click="emit('change', page - 1)">上一页</button>
    <span aria-live="polite">第 {{ page + 1 }} 页</span>
    <button type="button" :disabled="disabled || !hasNext" @click="emit('change', page + 1)">下一页</button>
  </nav>
</template>
<style scoped>
.workbench .list-pagination{display:flex;align-items:center;justify-content:flex-end;gap:12px;flex-wrap:wrap;padding:16px 0;color:var(--rf-muted);font-size:14px}
.workbench .list-pagination button{font:inherit;color:var(--rf-ink);background:white;border:1px solid var(--rf-line);border-radius:7px;padding:7px 12px;line-height:1.5;box-shadow:none;white-space:nowrap}
.workbench .list-pagination button:hover:not(:disabled){color:var(--rf-accent);border-color:var(--rf-accent);background:var(--rf-accent-soft)}
.workbench .list-pagination button:disabled{opacity:.4;cursor:default}
</style>
