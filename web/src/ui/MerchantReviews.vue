<script setup lang="ts">
import { useCursorPages } from '../cursor-pages'
import ListPagination from './ListPagination.vue'

import ReviewDialog from './ReviewDialog.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { reviewApi, type ProductReview } from '../review-client'
import './product-reviews.css'
const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: []; working: [value: boolean] }>()
const { pageIndex, pageCursor, acceptPage } = useCursorPages<number>()
const items = ref<ProductReview[]>([]), selected = ref<ProductReview | null>(null), next = ref<number | null>(null)
const body = ref(''), error = ref(''), notice = ref(''), loading = ref(false), writing = ref(false), conflict = ref(false), unknown = ref(false)
let alive = true, generation = 0, pending: { id: number; body: string; version: number } | null = null
const canSave = computed(() => selected.value && body.value.trim().length > 0 && body.value.trim().length <= 1000 && !writing.value && !loading.value && !conflict.value)
function failure(cause: unknown, fallback: string) { if (cause instanceof ApiError && cause.status === 401) emit('expired'); error.value = cause instanceof ApiError ? cause.message : fallback }
async function load(page = 0) {
  if (writing.value || unknown.value || loading.value) return
  const g = ++generation; loading.value = true; error.value = ''
  try {
    const result = await reviewApi.merchant(props.account.access_token, pageCursor(page), 8)
    if (alive && g === generation) { items.value = result.items; next.value = result.next_before; acceptPage(page, next.value); selected.value = null; body.value = ''; pending = null; notice.value = '' }
  } catch (cause) { if (alive && g === generation) failure(cause, '商品评价暂时无法读取，请重试。') }
  finally { if (alive && g === generation) loading.value = false }
}
const replyDrafts = new Map<number, string>()
function closeReply() { if (writing.value || unknown.value || !selected.value) return; replyDrafts.set(selected.value.review_id, body.value); selected.value = null }
function select(item: ProductReview) {
  if (writing.value || unknown.value) return
  if (selected.value) replyDrafts.set(selected.value.review_id, body.value)
  selected.value = item; body.value = replyDrafts.get(item.review_id) ?? item.reply ?? ''; error.value = ''; notice.value = ''; conflict.value = false; pending = null
}
async function current() {
  if (!selected.value || writing.value) return
  const id = selected.value.review_id, g = generation
  loading.value = true; error.value = ''; notice.value = ''
  try {
    const result = await reviewApi.merchant(props.account.access_token, id + 1, 1)
    if (!alive || g !== generation || selected.value?.review_id !== id) return
    const fresh = result.items.find(i => i.review_id === id)
    if (!fresh) throw new Error('missing original review')
    selected.value = fresh; items.value = items.value.map(i => i.review_id === id ? fresh : i)
    conflict.value = false; unknown.value = false; pending = null; notice.value = '已读取当前评价，本地回复已保留，请核对后保存。'
  } catch (cause) { if (alive && g === generation) failure(cause, '原评价暂时无法读取，请重试。') }
  finally { if (alive && g === generation) loading.value = false }
}
async function save() {
  if (!canSave.value || !selected.value) return
  if (!pending) pending = { id: selected.value.review_id, body: body.value.trim(), version: selected.value.version }
  const request = pending, g = generation
  writing.value = true; emit('working', true); error.value = ''; notice.value = ''
  try {
    const result = await reviewApi.reply(props.account.access_token, request.id, request.body, request.version)
    if (!alive || g !== generation) return
    selected.value = result; items.value = items.value.map(i => i.review_id === result.review_id ? result : i)
    body.value = result.reply ?? ''; replyDrafts.delete(result.review_id); pending = null; unknown.value = false; notice.value = '回复已保存。'
  } catch (cause) {
    if (!alive || g !== generation) return
    if (cause instanceof ApiError && cause.status < 500) { conflict.value = cause.status === 409; pending = null; unknown.value = false; failure(cause, '') }
    else { unknown.value = true; error.value = '回复结果尚未确认，请用原内容确认，或读取当前评价。' }
  } finally { if (alive && g === generation) { writing.value = false; emit('working', false) } }
}
watch(() => props.account.access_token, () => { ++generation; items.value = []; selected.value = null; pending = null; unknown.value = false; conflict.value = false; notice.value = ''; void load() }, { immediate: true })
onBeforeUnmount(() => { alive = false; ++generation; emit('working', false) })
</script>
<template>
  <main class="merchant-reviews">
    <h1>商品评价</h1>
    <p v-if="loading" role="status">正在读取评价…</p><p v-if="error && !selected" class="review-error" role="alert">{{ error }}</p><p v-if="notice && !selected" class="review-notice" role="status">{{ notice }}</p>
    <div class="review-columns">
      <section class="product-reviews"><h2>买家反馈</h2><p v-if="!loading && !items.length && !error" class="review-muted">本店暂无商品评价。</p>
        <article v-for="item in items" :key="item.review_id" class="review-entry"><button class="review-select" data-test="select-review" :aria-pressed="selected?.review_id === item.review_id" :disabled="writing || unknown || loading" @click="select(item)"><strong>{{ item.product_name }} · {{ item.variant }}</strong><p class="review-stars">{{ item.rating }} 星 · {{ item.reply ? '已回复' : '待回复' }}</p><p class="review-body">{{ item.body }}</p><span class="review-muted">已购用户 · {{ new Date(item.updated_at).toLocaleDateString('zh-CN') }}</span></button><div v-if="item.reply" class="review-reply"><strong>商家回复</strong><p>{{ item.reply }}</p></div></article>
        <ListPagination :page="pageIndex" :has-next="!!next" :disabled="loading || writing || unknown" label="商品评价分页" @change="load" /><button v-if="error && !selected" class="review-button" :disabled="loading" @click="load()">重新读取</button>
      </section>
      <ReviewDialog v-if="selected" title="回复买家评价" :busy="writing || unknown" @close="closeReply"><div class="review-editor"><p v-if="error" class="review-error" role="alert">{{ error }}</p><p v-if="notice" class="review-notice" role="status">{{ notice }}</p><p><strong>{{ selected.product_name }} · {{ selected.rating }} 星</strong></p><p class="review-body">{{ selected.body }}</p><p v-if="selected.reply" class="review-body">当前回复：{{ selected.reply }}</p><form @submit.prevent="save"><label for="merchant-review-reply">公开回复</label><textarea id="merchant-review-reply" v-model="body" maxlength="1000" :disabled="writing || unknown || loading" placeholder="认真回应买家的实际反馈…" /><div class="review-actions"><button data-test="save-reply" class="review-button review-primary" :disabled="!canSave" type="submit">{{ writing ? '正在保存…' : unknown ? '用原内容确认结果' : '发布回复' }}</button></div></form><button v-if="conflict || unknown" data-test="refresh-review" class="review-button" :disabled="loading || writing" @click="current">读取当前评价</button></div></ReviewDialog>
    </div>
  </main>
</template>
