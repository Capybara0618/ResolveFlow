import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import ProductArt from '../src/ui/ProductArt.vue'

it('switches product identity between exact color variants', async () => {
  const wrapper = mount(ProductArt, { props: { asset: 'headphones', name: '无线降噪耳机', variant: '黑色' } })
  expect(wrapper.get('img').attributes('src')).toContain('headphones-black.webp')
  await wrapper.setProps({ variant: '银色' })
  expect(wrapper.get('img').attributes('src')).toContain('headphones-silver.webp')
  expect(wrapper.get('img').attributes('alt')).toContain('银色')
})

it('keeps legacy illustration for a different product sharing the same asset key', () => {
  const wrapper = mount(ProductArt, { props: { asset: 'basket', name: '桌面收纳盒', variant: '三层款' } })
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('svg').exists()).toBe(true)
})

it('does not show a default color for an unsupported historical variant', () => {
  const wrapper = mount(ProductArt, { props: { asset: 'headphones', name: '无线降噪耳机', variant: '红色' } })
  expect(wrapper.find('img').exists()).toBe(false)
})

it('falls back on image failure and can show a different valid variant', async () => {
  const wrapper = mount(ProductArt, { props: { asset: 'headphones', name: '无线降噪耳机' } })
  await wrapper.get('img').trigger('error')
  expect(wrapper.find('svg').exists()).toBe(true)
  await wrapper.setProps({ variant: '银色' })
  expect(wrapper.get('img').attributes('src')).toContain('headphones-silver.webp')
})
