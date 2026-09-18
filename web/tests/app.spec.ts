import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import App from '../src/App.vue'

describe('App', () => {
  it('renders the case rows with formatted money', () => {
    const wrapper = mount(App)

    expect(wrapper.text()).toContain('c-9001')
    expect(wrapper.text()).toContain('REFUND')
    expect(wrapper.text()).toContain('200.00 CNY')
  })

  it('shows a total computed from integer minor units', () => {
    const wrapper = mount(App)

    expect(wrapper.text()).toContain('合计：200.00 CNY')
  })
})
