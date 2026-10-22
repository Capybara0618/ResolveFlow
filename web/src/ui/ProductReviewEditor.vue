<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '../client'
import { reviewApi, type OwnReview, type ReviewWrite } from '../review-client'
import './product-reviews.css'
const props = defineProps<{ token: string; line: string; name: string }>()
const emit = defineEmits<{ expired: []; working: [value: boolean]; close: [] }>()
const state = ref<OwnReview | null>(null), body = ref(''), rating = ref(5), error = ref(''), notice = ref('')
const loading = ref(false), writing = ref(false), editing = ref(false), conflict = ref(false), unknown = ref(false)
let generation = 0, alive = true, pending: ReviewWrite | null = null
const valid = computed(() => state.value?.can_review && body.value.trim().length > 0 && body.value.trim().length <= 1000 && Number.isInteger(rating.value) && rating.value >= 1 && rating.value <= 5 && !conflict.value && !loading.value && !writing.value)
async function load(preserve = false) {
  const g = ++generation; loading.value = true; error.value = ''; notice.value = ''
  if (!preserve) state.value = null
  try {
    const result = await reviewApi.own(props.token, props.line)
    if (!alive || g !== generation) return
    state.value = result; conflict.value = false; unknown.value = false; pending = null
    if (!preserve) { body.value = result.review?.body ?? ''; rating.value = result.review?.rating ?? 5; editing.value = !result.review }
    else { editing.value = true; notice.value = '已读取当前评价，本地输入已保留，请核对后保存。' }
  } catch (cause) {
    if (!alive || g !== generation) return
    if (cause instanceof ApiError && cause.status === 401) emit('expired')
    error.value = '评价资格暂时无法读取，请重试。'
  } finally { if (alive && g === generation) loading.value = false }
}
async function save() {
  if (!valid.value) return
  if (!pending) pending = { rating: rating.value, body: body.value.trim(), expected_version: state.value?.review?.version ?? 0 }
  const request = pending, g = generation
  writing.value = true; emit('working', true); error.value = ''; notice.value = ''
  try {
    const result = await reviewApi.save(props.token, props.line, request)
    if (!alive || g !== generation) return
    state.value = { can_review: true, blocked_reason: null, review: result }
    editing.value = false; unknown.value = false; pending = null; notice.value = '评价已保存。'
  } catch (cause) {
    if (!alive || g !== generation) return
    if (cause instanceof ApiError && cause.status < 500) {
      pending = null; unknown.value = false; conflict.value = cause.status === 409
      if (cause.status === 401) emit('expired')
      error.value = cause.message
    } else { unknown.value = true; error.value = '保存结果尚未确认，请用原内容确认，或读取当前评价。' }
  } finally { if (alive && g === generation) { writing.value = false; emit('working', false) } }
}
watch(() => [props.token, props.line], () => { pending = null; unknown.value = false; conflict.value = false; void load() }, { immediate: true })
onBeforeUnmount(() => { alive = false; ++generation; emit('working', false) })
</script>
<template>
  <section class="product-reviews review-editor" aria-label="评价商品">
    <h2>{{ name }} · 商品评价</h2>
    <p v-if="loading" role="status">正在读取本人评价与资格…</p>
    <p v-if="notice" class="review-notice" role="status">{{ notice }}</p>
    <p v-if="error" class="review-error" role="alert">{{ error }}</p>
    <p v-if="state && !state.can_review" class="review-muted">{{ state.blocked_reason }}</p>
    <div v-if="state?.review" class="review-reply"><strong>当前已保存评价 · {{ state.review.rating }} 星</strong><p>{{ state.review.body }}</p><p v-if="state.review.reply">商家回复：{{ state.review.reply }}</p></div>
    <form v-if="state?.can_review && editing" @submit.prevent="save">
      <label>商品评分 <select v-model.number="rating" aria-label="商品评分" :disabled="writing || unknown || loading"><option v-for="n in [5,4,3,2,1]" :key="n" :value="n">{{ n }} 星</option></select></label>
      <label :for="`review-${line}`">评价内容</label><textarea :id="`review-${line}`" v-model="body" maxlength="1000" aria-label="评价内容" :disabled="writing || unknown || loading" placeholder="分享实际购买与使用体验…" />
      <div class="review-actions"><button class="review-button review-primary" data-test="review-save" :disabled="!valid" type="submit">{{ writing ? '正在保存…' : unknown ? '用原内容确认结果' : '保存评价' }}</button></div>
    </form>
    <div class="review-actions">
      <button v-if="state?.can_review && !editing" class="review-button" :disabled="writing || loading" @click="editing = true; notice = ''; body = state.review?.body ?? ''; rating = state.review?.rating ?? 5">修改评价</button>
      <button v-if="error || conflict || unknown" class="review-button" data-test="review-refresh" :disabled="writing || loading" @click="load(editing)">读取当前评价</button>
      <button class="review-button" :disabled="writing" @click="emit('close')">关闭评价</button>
    </div>
    <p class="review-muted">公开展示为“已购用户”。每个已签收订单行一条评价，可修改；退款后已发表评价保留。</p>
  </section>
</template>
