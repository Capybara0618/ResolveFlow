<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { reviewApi, type ProductReview, type ReviewSummary } from '../review-client'
import './product-reviews.css'
import UserAvatar from './UserAvatar.vue'
const props = defineProps<{ product: string }>()
const emit = defineEmits<{ summary: [value: ReviewSummary] }>()
const items = ref<ProductReview[]>([]), summary = ref<ReviewSummary | null>(null), next = ref<number | null>(null)
const loading = ref(false), error = ref('')
let generation = 0, alive = true
async function load(reset = true) {
  const g = reset ? ++generation : generation, product = props.product
  if (reset) { items.value = []; summary.value = null; next.value = null }
  loading.value = true; error.value = ''
  try {
    const result = await reviewApi.public(product, reset ? undefined : next.value ?? undefined)
    if (!alive || g !== generation) return
    if (!result.summary) throw new Error('missing summary')
    items.value = reset ? result.items : [...items.value, ...result.items]
    summary.value = result.summary; next.value = result.next_before
    emit('summary', result.summary)
  } catch { if (alive && g === generation) error.value = '评价暂时无法读取，请重试。' }
  finally { if (alive && g === generation) loading.value = false }
}
watch(() => props.product, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { alive = false; ++generation })
</script>
<template>
  <section class="product-reviews" aria-label="买家评价">
    <h2>买家评价</h2>
    <p v-if="loading && !summary" role="status">正在读取评价…</p>
    <div v-if="summary && summary.count" class="review-summary">
      <div><strong class="review-score">{{ summary.average?.toFixed(1) }}</strong><span> / 5</span><p>{{ summary.count }} 条已购评价</p></div>
      <div class="review-distribution"><label v-for="(count, index) in summary.stars" :key="index"><span>{{ 5 - index }} 星</span><meter min="0" :max="summary.count" :value="count" :aria-label="`${5 - index}星 ${count}条`" /><span>{{ count }}</span></label></div>
    </div>
    <p v-else-if="summary && !summary.count" class="review-muted">暂无评价，期待买家分享使用体验。</p>
    <article v-for="item in items" :key="item.review_id" class="review-entry">
      <div class="review-meta"><span class="review-buyer"><UserAvatar name="已购用户" :size="30" />已购用户 · {{ item.variant }}</span><time>{{ new Date(item.updated_at).toLocaleDateString('zh-CN') }}</time></div>
      <p class="review-stars" :aria-label="`${item.rating}星`">{{ '★'.repeat(item.rating) }}{{ '☆'.repeat(5 - item.rating) }}</p>
      <p class="review-body">{{ item.body }}</p>
      <div v-if="item.reply" class="review-reply"><strong>商家回复</strong><p>{{ item.reply }}</p></div>
    </article>
    <p v-if="error" class="review-error" role="alert">{{ error }} <button class="review-button" :disabled="loading" @click="load(!items.length)">重新读取评价</button></p>
    <button v-else-if="next" class="review-button" :disabled="loading" @click="load(false)">{{ loading ? '正在读取…' : '加载更多评价' }}</button>
  </section>
</template>

<style scoped>.review-buyer{display:inline-flex;align-items:center;gap:10px}</style>
