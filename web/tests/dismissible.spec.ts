import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { expect, it } from 'vitest'
import { useDismissible } from '../src/ui/useDismissible'

it('keeps inside interaction open, dismisses outside and Escape, and removes listeners', async () => {
  const w = mount(defineComponent({ setup() {
    const root = ref<HTMLElement>(), open = ref(true)
    useDismissible(root, () => open.value, () => { open.value = false })
    return { root, open }
  }, template: '<section ref="root"><button @click="open = true">打开</button><div v-if="open">消息</div></section>' }), { attachTo: document.body })
  await w.get('button').trigger('pointerdown'); expect(w.text()).toContain('消息')
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true })); await w.vm.$nextTick()
  expect(w.text()).not.toContain('消息')
  await w.get('button').trigger('click'); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await w.vm.$nextTick()
  expect(w.text()).not.toContain('消息'); expect(document.activeElement).toBe(w.get('button').element)
  w.unmount()
})
