export interface NavigationItem {
  path: string
  label: string
  icon: string
  roles: string[]
}

const customer = '\u5ba2\u6237'
const advisor = '\u7406\u8d22\u987e\u95ee'
const manager = '\u5ba2\u6237\u7ecf\u7406'
const risk = '\u98ce\u63a7\u4e13\u5458'
const admin = '\u7ba1\u7406\u5458'

export const navigationItems: NavigationItem[] = [
  { path: '/chat', label: 'AI \u8d22\u5bcc\u52a9\u624b', icon: 'spark', roles: [customer, advisor, manager, risk, admin] },
  { path: '/dashboard', label: '\u667a\u80fd\u8fd0\u8425\u4e2d\u5fc3', icon: 'grid', roles: [advisor, manager, risk, admin] },
  { path: '/profile', label: '\u5ba2\u6237\u753b\u50cf', icon: 'user', roles: [customer, advisor, manager, risk, admin] },
  { path: '/advisor', label: '\u987e\u95ee\u5de5\u4f5c\u53f0', icon: 'briefcase', roles: [advisor, admin] },
  { path: '/operations', label: '\u4e1a\u52a1\u529e\u7406\u4e0e\u5ba1\u6279', icon: 'workflow', roles: [manager, admin] },
  { path: '/risk', label: '\u98ce\u9669\u7ba1\u7406', icon: 'shield', roles: [risk, admin] },
  { path: '/analytics', label: '\u6570\u636e\u5206\u6790', icon: 'chart', roles: [advisor, manager, risk, admin] },
  { path: '/knowledge', label: '\u77e5\u8bc6\u5e93', icon: 'book', roles: [admin] },
]

export function navigationForRole(role: string): NavigationItem[] {
  return navigationItems.filter((item) => item.roles.includes(role))
}

const roleHome: Record<string, string> = {
  [customer]: '/chat',
  [advisor]: '/advisor',
  [manager]: '/operations',
  [risk]: '/risk',
  [admin]: '/knowledge',
}

export function homeForRole(role: string): string {
  return roleHome[role] || navigationForRole(role)[0]?.path || '/login'
}
