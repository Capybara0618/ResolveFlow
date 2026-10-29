<script setup lang="ts">
import type { LoginResponse } from '../client'
import UserAvatar from './UserAvatar.vue'
defineProps<{ account: LoginResponse }>()
const emit = defineEmits<{ navigate: [hash: string] }>()
const links = [
  { title: '我的订单', hash: '#/shop/orders' }, { title: '售后申请', hash: '#/customer/applications' },
  { title: '售后咨询', hash: '#/shop/support' }, { title: '消息', hash: '#/shop/messages' },
  { title: '个人资料', hash: '#/shop/profile' }, { title: '收货地址', hash: '#/shop/addresses' },
]
const stages = [{ name: '待付款', status: 'WAITING_PAYMENT' }, { name: '待发货', status: 'AWAITING_SHIPMENT' }, { name: '待收货', status: 'AWAITING_RECEIPT' }, { name: '已完成', status: 'COMPLETED' }, { name: '售后', status: 'AFTER_SALES' }]
</script>
<template><main class="personal-center"><header><UserAvatar :token="account.access_token" source="/api/v1/account/avatar" :name="account.display_name" :size="64" /><div><h1>{{ account.display_name || '我的账户' }}</h1><button @click="emit('navigate', '#/shop/profile')">编辑资料</button></div></header><section class="personal-orders" aria-label="购物阶段"><h2>我的订单</h2><div><button v-for="stage in stages" :key="stage.status" @click="emit('navigate', `#/shop/orders?status=${stage.status}`)">{{ stage.name }}</button></div></section><nav aria-label="个人中心"><a v-for="link in links" :key="link.hash" :href="link.hash" @click.prevent="emit('navigate', link.hash)">{{ link.title }}</a></nav></main></template>
<style scoped>.personal-center{max-width:900px;margin:0 auto;padding:40px 24px;color:#293d34}.personal-center header{display:flex;align-items:center;gap:20px;margin:10px 0 32px}.personal-center h1{font-size:24px;margin:0 0 8px}.personal-center h2{font-size:18px}.personal-center button{font:inherit;cursor:pointer;border:0;background:none;color:#205e50}.personal-orders{padding:24px;background:#fff;border:1px solid #e1e5dc;border-radius:12px;margin-bottom:24px}.personal-orders>div{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.personal-orders button{padding:14px 0}.personal-center nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.personal-center nav a{display:block;padding:24px;background:#fff;border:1px solid #e1e5dc;border-radius:12px;text-decoration:none;color:inherit}.personal-center nav a:hover{border-color:#729281}@media(max-width:600px){.personal-center nav{grid-template-columns:1fr}.personal-orders>div{justify-content:flex-start;gap:20px}}</style>
