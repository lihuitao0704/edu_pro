export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
  trace_id: string
}

export interface AuthUser {
  user_id: number
  username: string
  real_name?: string
  role: '客户' | '理财顾问' | '客户经理' | '风控专员' | '管理员'
}

export interface RegisterPayload {
  username: string
  password: string
  real_name: string
  phone?: string
}

export interface Customer {
  customer_id: number
  username: string
  real_name?: string
  phone?: string
  age?: number
  occupation?: string
  customer_level?: string
  risk_level?: string
  risk_score?: number
  total_assets?: number
  confidence_score?: number
  risk_flag?: string
}

export interface Holding {
  id: number
  product_id: number
  product_code: string
  product_name: string
  product_type: string
  risk_level: string
  shares: number
  cost_amount: number
  current_value: number
  profit_loss?: number
  profit_ratio?: number
  status: string
}

export interface RiskAlert {
  alert_id: string
  customer_id: number
  alert_level: 'low' | 'medium' | 'high'
  trigger_rules: Array<{ rule_id: string; rule_name: string }>
  summary: string
  status: string
  created_at: string
}
