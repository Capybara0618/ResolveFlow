<script setup lang="ts">
import type { OrderLine } from '../client'
import { formatMinorUnits } from '../money'
import { productTitle, variantOf, productNameMissing } from './order-line-format'
import ProductArt from './ProductArt.vue'
import Icon from './ReviewIcon.vue'

withDefaults(defineProps<{ line?: OrderLine | null; loading?: boolean; unavailable?: boolean; store?: string; showAmount?: boolean }>(), { showAmount: true })
</script>

<template>
  <div class="aftercare-product" :aria-busy="loading">
    <div class="aftercare-product-image">
      <ProductArt v-if="line?.asset_key" :asset="line.asset_key" :name="productTitle(line)" :variant="variantOf(line) || ''" />
      <span v-else class="aftercare-product-placeholder" aria-label="商品图片未提供"><Icon name="box" :size="32" /><span>{{ loading ? '读取中' : '图片未提供' }}</span></span>
    </div>
    <div class="aftercare-product-copy">
      <span v-if="line?.merchant_name || store" class="aftercare-product-store" data-test="order-store">{{ line?.merchant_name || store }}</span>
      <strong data-test="order-product" :class="{ 'name-missing': line && productNameMissing(line) }">{{ line ? productTitle(line) : loading ? '正在读取商品…' : '商品资料暂不可用' }}</strong>
      <span v-if="line" class="aftercare-product-variant" :data-test="variantOf(line) ? 'order-variant' : undefined">{{ variantOf(line) || '规格未提供' }} · 数量 × {{ line.quantity }}</span>
      <span v-else-if="unavailable" class="aftercare-product-variant">申请记录仍可查看</span>
      <span v-if="line && showAmount !== false" class="aftercare-product-amount">本行实付 <b>{{ formatMinorUnits(line.line_paid_amount, line.currency) }}</b></span>
    </div>
  </div>
</template>

<style>
.aftercare-product { display: flex; align-items: center; gap: 22px; min-width: 0; }
.aftercare-product-image { width: 116px; height: 116px; flex: 0 0 116px; display: grid; place-items: center; background: var(--rf-subtle); border-radius: 12px; overflow: hidden; }
.aftercare-product-image .product-art { width: 100%; height: 100%; }
.aftercare-product-placeholder { display: grid; justify-items: center; gap: 8px; color: var(--rf-muted); font-size: 16px; }
.aftercare-product-copy { display: grid; gap: 9px; min-width: 0; line-height: 1.5; }
.aftercare-product-copy strong { font-size: 19px; color: var(--rf-ink); overflow-wrap: anywhere; }
.aftercare-product-store { color: var(--rf-accent); font-size: 16px; font-weight: 600; }
.aftercare-product-variant { color: var(--rf-muted); font-size: 16px; overflow-wrap: anywhere; }
.aftercare-product-amount { font-size: 16px; color: var(--rf-muted); }
.aftercare-product-amount b { margin-left: 10px; color: var(--rf-ink); font-size: 22px; }
</style>
