<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 18 })
const paths: Record<string, string> = {
  queue: 'M8 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3M9 2h6v4H9zM7 11h10M7 15h6',
  search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  bell: 'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4',
  chevron: 'm9 5 7 7-7 7', down: 'm6 9 6 6 6-6',
  check: 'm5 12 4 4L19 6', close: 'm6 6 12 12M6 18 18 6',
  file: 'M14 2H5v20h14V7zM14 2v6h5M8 12h8M8 16h6',
  image: 'M3 3h18v18H3zM3 17l6-6 4 4 3-3 5 5M8 7h.01',
  shield: 'M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6zM8 12l3 3 5-6',
  copy: 'M8 8h13v13H8zM4 16H2V2h14v2',
  sparkle: 'm12 2 2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z',
  clock: 'M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  box: 'm12 2 10 5v10l-10 5-10-5V7zM2 7l10 5 10-5M12 12v10M7 4.5l10 5',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  user: 'M20 21v-2a6 6 0 0 0-6-6h-4a6 6 0 0 0-6 6v2M16 5a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
}
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.file" /></svg>
</template>
