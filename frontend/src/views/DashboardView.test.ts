import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import DashboardView from './DashboardView.vue'

const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/http', () => ({ get }))

describe('DashboardView', () => {
  it('loads business, health and trace data while labelling mock agent cards', async () => {
    get.mockImplementation((path: string) => {
      if (path === '/analytics/bi/dashboard') {
        return Promise.resolve({
          summary: {
            total_customers: 100,
            total_aum: 2230000,
            total_alerts: 206,
            in_sale_products: 88,
          },
          alert_distribution: [{ name: 'high', count: 81, label: '高风险' }],
          return_by_risk: [{ name: 'R1', avg_return: 4.2 }],
          monthly_trend: [{ month: '2026-07', tx_count: 25 }],
        })
      }
      if (path === '/admin/health') {
        return Promise.resolve({ status: 'healthy', checks: { mysql: 'ok' } })
      }
      return Promise.resolve({
        items: [{
          agent_name: 'advisor',
          session_id: 'session-1',
          status: 'ok',
          created_time: '2026-07-26T10:00:00',
        }],
      })
    })

    const wrapper = mount(DashboardView, {
      global: {
        stubs: {
          DashboardCard: {
            props: ['label', 'value', 'trend'],
            template: '<div class="metric">{{ label }}={{ value }}={{ trend }}</div>',
          },
          AgentCard: { template: '<div class="agent-card" />' },
          AgentTrace: {
            props: ['nodes'],
            template: '<div class="trace-count">{{ nodes.length }}</div>',
          },
          RiskPanel: {
            props: ['totalAlerts'],
            template: '<div class="risk-total">{{ totalAlerts }}</div>',
          },
          ChartPanel: { template: '<div class="chart-panel" />' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.classes()).toContain('workspace-page')
    expect(wrapper.get('[data-testid="dashboard-health"]').text()).toContain('服务')
    expect(get).toHaveBeenCalledWith('/analytics/bi/dashboard')
    expect(get).toHaveBeenCalledWith('/admin/health')
    expect(get).toHaveBeenCalledWith('/analytics/chat/traces')
    expect(wrapper.text()).toContain('核心服务检查正常')
    expect(wrapper.text()).toContain('服务客户=100=来自客户画像汇总')
    expect(wrapper.text()).toContain('在售产品=88=来自产品货架')
    expect(wrapper.text()).toContain('演示布局 · 非实时运行指标')
    expect(wrapper.find('.trace-count').text()).toBe('1')
    expect(wrapper.find('.risk-total').text()).toBe('206')
  })
})
