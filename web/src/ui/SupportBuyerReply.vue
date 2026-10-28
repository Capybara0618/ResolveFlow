<script setup lang="ts">
import { computed } from 'vue'
import type { SupportMessage } from '../support-client'
import { buyerParts } from '../support-view'

const props = defineProps<{ message: SupportMessage }>()
const parts = computed(() => buyerParts(props.message))
</script>

<template>
  <template v-if="parts">
    <div v-for="part in parts" :key="part.task_id" class="support-reply-part">
      <p>{{ part.text }}</p>
      <p v-if="part.guidance" class="support-reply-guidance">{{ part.guidance }}</p>
    </div>
  </template>
  <p v-else>{{ message.text }}</p>
</template>

<style scoped>
.support-reply-part + .support-reply-part { margin-top: 18px; }
.support-reply-part > .support-reply-guidance { margin-top: 10px; }
</style>
