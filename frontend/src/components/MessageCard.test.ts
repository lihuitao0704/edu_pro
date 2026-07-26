import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MessageCard from './MessageCard.vue'

describe('MessageCard', () => {
  it('does not duplicate a recommendation already rendered in the assistant reply', () => {
    const wrapper = mount(MessageCard, {
      props: {
        message: {
          role: 'assistant',
          content: '### 适合您的产品\n1. **稳健债券A**（R2）',
          response: {
            answer: '已完成推荐',
            agent: 'advisor',
            confidence: 0.9,
            suggestions: [],
            metadata: {
              recommendation: {
                title: '智能匹配产品建议',
                risk_level: '稳健型',
                product: '稳健债券A',
                allocation: '参考年化 4.2%',
                rationale: '与您的风险承受能力匹配。',
              },
            },
          },
        },
      },
      global: {
        stubs: { DataTableModal: true },
      },
    })

    expect(wrapper.text()).toContain('稳健债券A')
    expect(wrapper.find('.recommendation-card').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('智能匹配产品建议')
  })
})
