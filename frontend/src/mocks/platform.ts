export interface AgentSummary {
  name: string
  code: string
  description: string
  status: 'Online' | 'Degraded'
  calls: number
  latency: string
  successRate: number
  accent: string
}

export interface TraceNode {
  name: string
  action: string
  duration: string
  result: 'success' | 'processing'
}

export const agentDirectory: AgentSummary[] = [
  { name: '客服 Agent', code: 'SERVICE', description: '产品知识与服务问答', status: 'Online', calls: 1284, latency: '680 ms', successRate: 0.996, accent: 'blue' },
  { name: '投顾 Agent', code: 'INVEST', description: '适配方案与投资建议', status: 'Online', calls: 520, latency: '1.28 s', successRate: 0.984, accent: 'violet' },
  { name: '风控 Agent', code: 'RISK', description: '风险识别与合规校验', status: 'Online', calls: 376, latency: '840 ms', successRate: 0.993, accent: 'red' },
  { name: '数据分析 Agent', code: 'DATA', description: '经营洞察与数据查询', status: 'Online', calls: 218, latency: '1.65 s', successRate: 0.978, accent: 'cyan' },
  { name: '业务操作 Agent', code: 'OPS', description: '账户业务与流程编排', status: 'Online', calls: 164, latency: '920 ms', successRate: 0.989, accent: 'amber' },
]

export const executionTrace: TraceNode[] = [
  { name: '用户问题', action: '我有 50 万，如何稳健配置？', duration: '0 ms', result: 'success' },
  { name: 'Router Agent', action: '识别意图：投资建议', duration: '124 ms', result: 'success' },
  { name: 'Investment Agent', action: '加载用户画像与适当性等级', duration: '312 ms', result: 'success' },
  { name: '产品库检索', action: '筛选 12 个适配产品', duration: '486 ms', result: 'success' },
  { name: '风险校验', action: '组合波动与集中度检查通过', duration: '261 ms', result: 'success' },
  { name: '生成建议', action: '形成稳健增值配置方案', duration: '198 ms', result: 'success' },
]

export const platformMetrics = [
  { label: '服务用户', value: '28,640', trend: '+12.8%', tone: 'blue' },
  { label: 'Agent 调用', value: '2,562', trend: '+18.4%', tone: 'violet' },
  { label: '风险事件', value: '36', trend: '-8.2%', tone: 'red' },
  { label: '产品推荐', value: '1,208', trend: '+9.6%', tone: 'cyan' },
]

export const requestTrend = [422, 468, 446, 514, 578, 652, 624]
export const intentMix = [
  { name: '投资建议', value: 42 },
  { name: '产品咨询', value: 28 },
  { name: '风险评估', value: 18 },
  { name: '账户业务', value: 12 },
]
export const riskRadar = [82, 74, 88, 91, 79]
