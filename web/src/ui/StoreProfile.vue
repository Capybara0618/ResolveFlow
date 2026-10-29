<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { presentationApi, type StorePresentation } from '../presentation-client'
import CatalogImage from './CatalogImage.vue'
import UserAvatar from './UserAvatar.vue'
const props = defineProps<{ id: string; name: string; description: string }>()
const emit = defineEmits<{ contact: [] }>()
const profile = ref<StorePresentation | null>(null), error = ref(false)
let generation = 0
async function load() { const g = ++generation; profile.value = null; error.value = false; try { const p = await presentationApi.store(props.id); if (g === generation) profile.value = p } catch { if (g === generation) error.value = true } }
watch(() => props.id, load, { immediate: true }); onBeforeUnmount(() => { generation++ })
</script>
<template><section class="store-profile"><div class="store-profile-logo"><CatalogImage v-if="profile?.logo_id" :id="profile.logo_id" :name="name" /><UserAvatar v-else kind="MERCHANT" :name="name" :size="64" /></div><div><h1>{{ name }}</h1><p>{{ profile?.introduction || description }}</p><p v-if="profile?.service_hours">营业时间 {{ profile.service_hours }}</p><a v-if="profile?.contact_phone" :href="`tel:${profile.contact_phone}`">{{ profile.contact_phone }}</a><button @click="emit('contact')">订单售后咨询</button><p v-if="error" role="status">店铺资料暂时无法读取 <button @click="load">重试</button></p></div></section></template>
<style scoped>.store-profile{display:flex;align-items:flex-start;gap:22px;padding:28px 0 36px}.store-profile-logo{width:64px;height:64px;border-radius:50%;overflow:hidden;flex-shrink:0}.store-profile h1{font-size:28px;margin:0 0 12px}.store-profile p{font-size:15px;line-height:1.7;color:#667367;white-space:pre-wrap;margin:8px 0}.store-profile button{font:inherit;color:#205e50;background:none;border:1px solid #cdd9cd;border-radius:7px;padding:8px 14px;cursor:pointer;margin:12px 0 0}.store-profile a{display:block;color:#205e50;font-size:15px;margin-top:12px}</style>
