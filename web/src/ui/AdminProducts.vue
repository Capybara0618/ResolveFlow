<script setup lang="ts">
import { useCursorPages } from '../cursor-pages'
import ListPagination from './ListPagination.vue'

import { computed, onMounted, onBeforeUnmount, ref, useId } from 'vue'
import { ApiError, type LoginResponse } from '../client'
import { managementApi, type ManagedProduct, type ProductWrite } from '../management-client'
import ProductArt from './ProductArt.vue'
import ReviewDialog from './ReviewDialog.vue'
import PresentationEditor from './PresentationEditor.vue'
import './foundation.css'

const productFormId = useId()
const props = defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ expired: []; working: [value: boolean] }>()
const { pageIndex, pageCursor, acceptPage } = useCursorPages<string>()
const rows = ref<ManagedProduct[]>([]), after = ref<string | null>(null), busy = ref(false), error = ref(''), notice = ref('')
const presentation = ref<{ product?: string } | null>(null)
const edit = ref(false), selected = ref<ManagedProduct | null>(null), name = ref(''), description = ref(''), category = ref('electronics'), asset = ref('headphones'), listed = ref(true)
const skus = ref<Array<{ sku_id: string | null; variant: string; price: string; max_quantity: number; listed: boolean }>>([])
const assets = ['headphones', 'keyboard', 'mouse', 'lamp', 'cup', 'pillow', 'speaker', 'charger', 'monitor', 'hub', 'powerbank', 'stand', 'webcam', 'basket', 'clock', 'blanket', 'vase', 'tray', 'backpack', 'tent', 'chair', 'mat', 'bottle', 'lantern', 'umbrella', 'bag', 'pole', 'hat']
const assetLabels: Record<string, string> = {"headphones": "耳机", "keyboard": "键盘", "mouse": "鼠标", "lamp": "台灯", "cup": "保温杯", "pillow": "靠枕", "speaker": "音箱", "charger": "充电器", "monitor": "显示器", "hub": "扩展坞", "powerbank": "充电宝", "stand": "支架", "webcam": "摄像头", "basket": "收纳篮", "clock": "挂钟", "blanket": "盖毯", "vase": "花瓶", "tray": "托盘", "backpack": "背包", "tent": "帐篷", "chair": "折叠椅", "mat": "垫子", "bottle": "水壶", "lantern": "露营灯", "umbrella": "雨伞", "bag": "收纳袋", "pole": "登山杖", "hat": "遮阳帽"}
let alive = true
onBeforeUnmount(() => { alive = false })
function cents(price: string) { if (!/^\d{1,7}(\.\d{1,2})?$/.test(price)) return null; const [whole, fraction = ''] = price.split('.'); const amount = Number(whole) * 100 + Number(fraction.padEnd(2, '0')); return amount > 0 && amount <= 100000000 ? amount : null }
const valid = computed(() => !!name.value.trim() && !!description.value.trim() && skus.value.length > 0 && skus.value.every(s => !!s.variant.trim() && cents(s.price) !== null && Number.isInteger(s.max_quantity) && s.max_quantity >= 1 && s.max_quantity <= 100) && (!listed.value || skus.value.some(s => s.listed)))
async function load(index = pageIndex.value) { const page = await managementApi.products(props.account.access_token, pageCursor(index)); if (alive) { rows.value = page.items; after.value = page.next_after; acceptPage(index, after.value) } }
async function act(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; emit('working', true); error.value = ''; notice.value = ''
  try { await work() } catch (cause) { if (alive && cause instanceof ApiError && cause.status === 401) emit('expired'); else if (alive) error.value = cause instanceof Error ? cause.message : '请求结果未确认，请刷新。' }
  finally { if (alive) { busy.value = false; emit('working', false) } }
}
function open(row: ManagedProduct | null) {
  selected.value = row ? { ...row, skus: row.skus.map(s => ({ ...s })) } : null; edit.value = true; name.value = row?.name ?? ''; description.value = row?.description ?? ''; category.value = row?.category ?? 'electronics'; asset.value = row?.asset_key ?? 'headphones'; listed.value = row?.listed ?? true
  skus.value = row ? row.skus.map(s => ({ sku_id: s.sku_id, variant: s.variant, price: (s.unit_amount / 100).toFixed(2), max_quantity: s.max_quantity, listed: s.listed })) : [{ sku_id: null, variant: '标准款', price: '', max_quantity: 10, listed: true }]
}
async function save() {
  if (!valid.value) return
  await act(async () => {
    const body: ProductWrite = { name: name.value, description: description.value, category: category.value, asset_key: asset.value, listed: listed.value, expected_version: selected.value?.version ?? null, skus: skus.value.map(s => ({ sku_id: s.sku_id, variant: s.variant, unit_amount: cents(s.price)!, max_quantity: s.max_quantity, listed: s.listed })) }
    await managementApi.saveProduct(props.account.access_token, selected.value?.product_id ?? null, body)
    if (alive) { edit.value = false; await load(); notice.value = '商品已保存' }
  })
}
onMounted(() => { void act(() => load()) })
</script>
<template>
  <main class="foundation-main">
    <header class="foundation-heading"><div><h1>商品管理</h1></div><div class="foundation-actions"><button :disabled="busy" @click="act(() => load())">刷新</button><button class="primary-button" :disabled="busy" @click="open(null)">新增商品</button><button :disabled="busy" @click="presentation = {}; edit = false">店铺资料</button></div></header>
    <p v-if="error && !edit" class="message error" role="alert">{{ error }}</p><p v-if="notice" class="message success" role="status">{{ notice }}</p>
    <ReviewDialog v-if="presentation" :title="presentation.product ? '商品图片与详情' : '店铺资料'" :busy="busy" merchant @close="presentation = null"><PresentationEditor embedded :key="presentation.product ?? 'store'" :account="account" :product="presentation.product" :variants="rows.find(row => row.product_id === presentation?.product)?.skus" @working="busy = $event; emit('working', $event)" @expired="emit('expired')" @close="presentation = null" /></ReviewDialog>
    <ReviewDialog :open="edit" :title="selected ? '编辑商品' : '新增商品'" :busy="busy" class="product-editor-dialog" @close="edit = false"><form :id="productFormId" class="foundation-editor" @submit.prevent="save">
      <p v-if="error" role="alert" class="message error">{{ error }}</p><fieldset :disabled="busy"><div class="foundation-fields">
        <label>商品名称<input v-model="name" required maxlength="120" /></label><label>商品分类<select v-model="category"><option value="electronics">数码</option><option value="home">家居</option><option value="outdoor">户外</option></select></label>
        <label class="span-two">商品介绍<textarea v-model="description" required maxlength="1000" /></label><label>商品图片<select v-model="asset"><option v-for="key in assets" :key="key" :value="key">{{ assetLabels[key] || key }}</option></select></label><label class="foundation-check"><input v-model="listed" type="checkbox" />商品上架</label>
      </div><h3>规格与价格</h3><div v-for="(sku, index) in skus" :key="sku.sku_id || index" class="foundation-sku-row"><label>规格<input v-model="sku.variant" required maxlength="120" /></label><label>单价（元）<input v-model="sku.price" inputmode="decimal" required /></label><label>限购数量<input v-model.number="sku.max_quantity" type="number" min="1" max="100" required /></label><label class="foundation-check"><input v-model="sku.listed" type="checkbox" />规格上架</label><button v-if="!sku.sku_id && skus.length > 1" type="button" :disabled="busy" @click="skus.splice(index, 1)">移除</button></div>
      <div class="foundation-actions"><button type="button" :disabled="busy || skus.length >= 20" @click="skus.push({ sku_id: null, variant: '', price: '', max_quantity: 10, listed: true })">添加规格</button></div>
    </fieldset></form><template #footer><button type="button" :disabled="busy" @click="edit = false">取消</button><button type="submit" :form="productFormId" class="primary-button" :disabled="busy || !valid">{{ busy ? '正在保存…' : '保存商品' }}</button></template></ReviewDialog>
    <div class="foundation-table-wrap"><table class="foundation-table"><thead><tr><th>商品</th><th>价格</th><th>规格</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.product_id"><td><div class="foundation-product-name"><ProductArt :asset="row.asset_key" :name="row.name" :variant="row.skus.find(s => s.listed)?.variant || row.skus[0]?.variant" /><strong>{{ row.name }}</strong></div></td><td>¥ {{ (Math.min(...row.skus.map(s => s.unit_amount)) / 100).toFixed(2) }}</td><td>{{ row.skus.length }} 个</td><td>{{ row.listed ? '已上架' : '已下架' }}</td><td><button :disabled="busy" @click="open(row)">编辑</button><button :disabled="busy" @click="presentation = { product: row.product_id }; edit = false">图片与详情</button></td></tr></tbody></table></div>
    <ListPagination :page="pageIndex" :has-next="!!after" :disabled="busy" label="商品管理分页" @change="index => act(() => load(index))" /><p v-if="!busy && rows.length === 0" class="empty">本店还没有商品，可以新增第一件。</p>
  </main>
</template>
