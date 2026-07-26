import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../stores/auth'
import OperationsView from './OperationsView.vue'

const { post } = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('../api/http', () => ({ post }))

describe('OperationsView', () => {
  beforeEach(() => {
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().user = {
      user_id: 9,
      username: 'admin',
      role: '管理员',
    } as any
    post.mockReset()
    HTMLElement.prototype.scrollTo = vi.fn()
  })

  function mountView() {
    return mount(OperationsView, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
  }

  it('redirects read-only requests to the wealth assistant without calling API', async () => {
    const wrapper = mountView()
    await wrapper.find('textarea').setValue('查询R2风险等级的产品')
    await wrapper.find('form').trigger('submit')

    expect(post).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('查询、推荐和分析请前往 AI 财富助手')
  })

  it('reuses the server session for operation confirmation', async () => {
    post
      .mockResolvedValueOnce({
        reply: '请确认申购参数',
        agent: 'operator',
        intent: 'business_operation',
        session_id: 'server-operation-session',
        data: {
          action: 'purchase_product',
          status: 'confirm_required',
          params: { customer_id: 120, amount: 100000 },
        },
      })
      .mockResolvedValueOnce({
        reply: '已确认执行',
        agent: 'operator',
        intent: 'business_operation',
        session_id: 'server-operation-session',
        data: { action: 'purchase_product', status: 'ok', params: {} },
      })
    const wrapper = mountView()

    await wrapper.find('textarea').setValue('给客户ID 1申购10万元产品 PROD-0001')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await wrapper.find('textarea').setValue('确认')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(post).toHaveBeenCalledTimes(2)
    expect(post.mock.calls[1][1]).toMatchObject({
      message: '确认',
      session_id: 'server-operation-session',
    })
    expect(wrapper.text()).toContain('等待确认')
    expect(wrapper.text()).toContain('处理完成')
  })
})
