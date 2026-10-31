import { defineComponent, ref } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { usePageEntrance } from '../src/ui/usePageEntrance'
import PageLoading from '../src/ui/PageLoading.vue'

let wrapper: VueWrapper | undefined
const calls: HTMLElement[] = []
let oldAnimate: typeof HTMLElement.prototype.animate
beforeEach(() => {
  calls.length = 0
  oldAnimate = HTMLElement.prototype.animate
  HTMLElement.prototype.animate = function() { calls.push(this); return { finished:Promise.resolve(), cancel:vi.fn() } as unknown as Animation }
  vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({top:10,bottom:100,height:90,width:400} as DOMRect)
  vi.stubGlobal('matchMedia', () => ({matches:false}))
})
afterEach(() => { wrapper?.unmount(); wrapper=undefined; HTMLElement.prototype.animate=oldAnimate; vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers() })

const Page = defineComponent({
  props:{page:{default:'orders'},loading:Boolean,inner:{default:'0'},draft:{default:''}},
  setup(props) { const root=ref<HTMLElement>(); usePageEntrance(()=>root.value,()=>props.page); return {root} },
  template:'<main ref="root" :data-page-loading="loading" :data-page-key="inner"><h1 data-page-reveal>{{page}}</h1><section data-page-reveal data-page-content>{{draft}}</section></main>',
})

it('reveals the shell first and waits for readiness on the surface itself before revealing data', async () => {
  wrapper=mount(Page,{props:{loading:true},attachTo:document.body}); await flushPromises()
  expect(calls.map(e=>e.tagName)).toEqual(['H1'])
  await wrapper.setProps({loading:false}); await flushPromises()
  expect(calls.map(e=>e.tagName)).toEqual(['H1','SECTION'])
})

it('does not replay entrance on refresh, message text or form changes', async () => {
  wrapper=mount(Page,{props:{loading:false},attachTo:document.body}); await flushPromises()
  const count=calls.length
  await wrapper.setProps({draft:'未保存的资料',loading:true}); await flushPromises()
  await wrapper.setProps({loading:false}); await flushPromises()
  expect(calls).toHaveLength(count)
  expect(wrapper.get('section').text()).toBe('未保存的资料')
})

it('cancels pending entrance when navigation changes and reveals only the current data', async () => {
  wrapper=mount(Page,{props:{loading:true},attachTo:document.body}); await flushPromises()
  await wrapper.setProps({page:'products'}); await flushPromises()
  await wrapper.setProps({loading:false,draft:'新页面数据'}); await flushPromises()
  expect(calls.filter(e=>e.tagName==='SECTION')).toHaveLength(1)
  expect(wrapper.get('h1').text()).toBe('products')
})

it('recognizes internal pagination without remounting the form or its draft', async () => {
  wrapper=mount(Page,{props:{draft:'保留输入'},attachTo:document.body}); await flushPromises()
  const root=wrapper.element, count=calls.length
  await wrapper.setProps({inner:'1'}); await flushPromises()
  expect(calls.length).toBeGreaterThan(count)
  expect(wrapper.element).toBe(root)
  expect(wrapper.get('section').text()).toBe('保留输入')
})

it('cleans its loading observer on unmount and honors reduced motion', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('matchMedia',()=>({matches:true}))
  wrapper=mount(Page,{props:{loading:true},attachTo:document.body}); await flushPromises()
  expect(calls).toHaveLength(0)
  wrapper.unmount(); wrapper=undefined
  expect(vi.getTimerCount()).toBe(0)
})

it('shows a skeleton only for a slow empty read and retains existing content during refresh', async () => {
  vi.useFakeTimers()
  wrapper=mount(PageLoading,{props:{loading:true,empty:true}})
  await vi.advanceTimersByTimeAsync(149); expect(wrapper.find('[data-page-placeholder]').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(1); expect(wrapper.get('[role="status"]').attributes('aria-label')).toBe('正在读取页面')
  await wrapper.setProps({empty:false}); expect(wrapper.find('[data-page-placeholder]').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(200); expect(wrapper.find('[data-page-placeholder]').exists()).toBe(false)
  await wrapper.setProps({loading:false}); expect(vi.getTimerCount()).toBe(0)
})
