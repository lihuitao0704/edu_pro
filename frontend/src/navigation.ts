export interface NavigationItem {
  path: string
  label: string
  icon: string
  roles: string[]
}

const ITEMS: NavigationItem[] = [
  { path: '/chat', label: '智能对话', icon: '◫', roles: ['客户', '理财顾问', '客户经理', '管理员'] },
  { path: '/profile', label: '客户画像', icon: '◎', roles: ['客户', '理财顾问', '客户经理', '风控专员', '管理员'] },
  { path: '/advisor', label: '顾问工作台', icon: '◇', roles: ['理财顾问', '管理员'] },
  { path: '/operations', label: '业务操作', icon: '↗', roles: ['理财顾问', '客户经理', '风控专员', '管理员'] },
  { path: '/risk', label: '风险管理', icon: '△', roles: ['风控专员', '管理员'] },
  { path: '/analytics', label: '数据分析', icon: '▥', roles: ['理财顾问', '客户经理', '风控专员', '管理员'] },
  { path: '/knowledge', label: '知识库', icon: '▤', roles: ['管理员'] },
]

export function navigationForRole(role: string): NavigationItem[] {
  return ITEMS.filter((item) => item.roles.includes(role))
}

const ROLE_HOME: Record<string, string> = {
  客户: '/chat',
  理财顾问: '/advisor',
  客户经理: '/operations',
  风控专员: '/risk',
  管理员: '/knowledge',
}

export function homeForRole(role: string): string {
  return ROLE_HOME[role] || navigationForRole(role)[0]?.path || '/login'
}
