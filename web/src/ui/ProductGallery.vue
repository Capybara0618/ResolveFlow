<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { presentationApi, type ProductPresentation } from '../presentation-client'
import ProductArt from './ProductArt.vue'
import CatalogImage from './CatalogImage.vue'
const props = defineProps<{ product: string; asset: string; name: string; variant?: string }>()
const details = ref<ProductPresentation | null>(null), selected = ref(0), error = ref(false)
let generation = 0
async function load() { const g = ++generation; details.value = null; selected.value = 0; error.value = false
  try { const value = await presentationApi.product(props.product); if (!Array.isArray(value.images) || !Array.isArray(value.specifications)) throw new Error('Invalid product details'); if (g === generation) details.value = value } catch { if (g === generation) error.value = true }
}
function selectVariant() { const image = props.variant && details.value?.variant_images?.[props.variant]; selected.value = Math.max(0, image ? details.value!.images.indexOf(image) : 0) }
watch([() => props.variant, details], selectVariant)
watch(() => props.product, load, { immediate: true }); onBeforeUnmount(() => { generation++ })
</script>
<template><div class="product-gallery"><div class="gallery-media"><div class="gallery-main"><CatalogImage v-if="details?.images.length" :id="details.images[selected]" :name="name" /><ProductArt v-else :asset="asset" :name="name" :variant="variant" /></div>
  <div v-if="details && details.images.length > 1" class="gallery-thumbnails" aria-label="商品图片"><button v-for="(id, index) in details.images" :key="id" :aria-label="`查看第${index + 1}张商品图片`" :aria-pressed="selected === index" @click="selected = index"><CatalogImage :id="id" :name="`${name} ${index + 1}`" /></button></div>
  </div><div class="gallery-information"><p v-if="error" role="status">商品详细资料暂时无法读取。<button @click="load">重试</button></p>
  <section v-if="details?.specifications.length" class="gallery-info"><h2>商品参数</h2><dl><div v-for="(spec, index) in details.specifications" :key="index"><dt>{{ spec.name }}</dt><dd>{{ spec.value }}</dd></div></dl></section>
  <section v-if="details?.shipping_note" class="gallery-info"><h2>配送说明</h2><p>{{ details.shipping_note }}</p></section><section v-if="details?.aftercare_note" class="gallery-info"><h2>售后说明</h2><p>{{ details.aftercare_note }}</p></section>
</div></div></template>
<style scoped>
.product-gallery{width:100%;min-width:0}.gallery-media{min-width:0}.gallery-main{aspect-ratio:1;background:#f0f1e9;overflow:hidden;border-radius:12px}.gallery-main>*{width:100%;height:100%;object-fit:contain}
.gallery-thumbnails{display:flex;gap:10px;overflow:auto;margin:14px 0}.gallery-thumbnails button{width:58px;height:58px;flex:0 0 58px;border:1px solid #d9dfd4;border-radius:7px;padding:3px;background:#fff;cursor:pointer}.gallery-thumbnails button[aria-pressed=true]{border-color:var(--rf-accent);box-shadow:inset 0 0 0 1px var(--rf-accent)}
.gallery-information{min-width:0}.gallery-info{margin:26px 0}.gallery-info h2{font-size:17px;font-weight:500;margin:0 0 16px}.gallery-info p{white-space:pre-wrap;font-size:14px;line-height:1.8;color:var(--rf-muted);max-width:900px}.gallery-info dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 40px;font-size:14px;margin:0}.gallery-info dl>div{display:grid;grid-template-columns:100px minmax(0,1fr);padding:13px 0;border-bottom:1px solid var(--rf-line);gap:16px}.gallery-info dt{color:var(--rf-muted)}.gallery-info dd{margin:0;overflow-wrap:anywhere}.product-gallery button{font:inherit;color:var(--rf-accent)}
@media(max-width:650px){.gallery-info dl{grid-template-columns:1fr}.gallery-info dl>div{grid-template-columns:86px minmax(0,1fr)}}
</style>
