# Light AI Wealth Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the complete Vue frontend into a responsive, light, premium AI wealth-workspace experience without changing business APIs, routing, or authorization behavior.

**Architecture:** Retain all current pages and data contracts. Add a small presentation layer for the application chrome and first-run intro, then replace global styling primitives so existing functional views inherit the light visual system. Make the dashboard the reference Bento page and apply the shared shell, states and responsive rules to every route.

**Tech Stack:** Vue 3, TypeScript, Vue Router, Pinia, Element Plus, ECharts, Vitest, Vite, CSS custom properties, Vue transitions.

## Global Constraints

- Preserve API paths, store contracts, routes, role navigation and authentication behavior.
- Use mist-white and blue-gray surfaces, graphite text, restrained indigo actions, and semantic status tokens.
- No Emoji icons, copied Codex/OpenAI assets, Three.js, large card radii or saturated decorative glow.
- Use only CSS/Vue transitions, respect `prefers-reduced-motion`, and animate only opacity or transform.
- Each behavior change begins with a failing Vitest test.

---

### Task 1: Add an accessible first-run intro

**Files:** Create `frontend/src/components/AppIntro.vue`, `frontend/src/components/AppIntro.test.ts`; modify `frontend/src/layouts/AppLayout.vue`.

**Produces:** `AppIntro` accepts `visible: boolean` and emits `complete`; AppLayout hides it after 1200ms, on Skip, or immediately for reduced-motion users.

- [ ] Write the failing test: mount `AppIntro` with `visible: true`; assert `[data-testid="app-intro"]` has `aria-label="平台正在启动"`; click its button and assert `complete` emitted once.
- [ ] Run `npm test -- AppIntro.test.ts`; expect component-resolution failure.
- [ ] Implement a `Transition`-wrapped `<section v-if="visible" data-testid="app-intro" aria-label="平台正在启动" role="status">` with a decorative grid, FINTELLIGENCE mark, readiness copy and a text Skip button; in AppLayout add `introVisible`, `matchMedia('(prefers-reduced-motion: reduce)')` handling and a timeout cleanup.
- [ ] Run `npm test -- AppIntro.test.ts`; expect PASS.
- [ ] Commit only these files with `feat: add accessible workspace intro`.

### Task 2: Rebuild global application chrome

**Files:** Modify `frontend/src/layouts/AppLayout.vue`, `frontend/src/navigation.ts`, `frontend/src/styles/index.css`; test `frontend/src/navigation.test.ts`.

**Produces:** Responsive sidebar/drawer, top context bar, labelled controls, connection state, and page title supplied by route metadata.

- [ ] Write a failing test iterating `navigationForRole('管理员')`, `navigationForRole('投顾')`, and `navigationForRole('客户')`; each item must have non-empty `label` and icon key.
- [ ] Run `npm test -- navigation.test.ts`; inspect expected failure, otherwise tighten it to the new compact navigation label contract.
- [ ] Add a top bar with a real labelled menu button, page context, connection pill and user avatar button. Preserve existing links and logout. Replace structural icon characters with consistent CSS/inline-SVG-compatible icon keys.
- [ ] Add `.workspace-topbar`, `.icon-button`, compact sidebar, drawer scrim and desktop/mobile breakpoints using Task 3 tokens.
- [ ] Run `npm test -- navigation.test.ts`; expect PASS; commit as `feat: refresh workspace navigation chrome`.

### Task 3: Establish light tokens and interaction foundation

**Files:** Modify `frontend/src/styles/index.css`, `frontend/src/views/DashboardView.vue`; test `frontend/src/views/DashboardView.test.ts`.

**Produces:** Semantic light tokens and reusable classes for cards, inputs, tables, dialogs, statuses, skeletons, focus, hover, page reveal and mobile grids.

- [ ] Write a failing test mounting DashboardView and asserting `.workspace-page` exists.
- [ ] Run `npm test -- DashboardView.test.ts`; expect selector failure.
- [ ] Add tokens: `--canvas:#f5f7fb`, `--surface:rgba(255,255,255,.78)`, `--surface-solid:#fff`, `--ink:#172033`, `--muted:#667085`, `--line:rgba(28,39,65,.10)`, `--primary:#3446a8`, `--primary-hover:#28398f`, `--shadow:0 18px 48px rgba(26,36,59,.08)`.
- [ ] Replace dark-theme override blocks with light token-driven styles. Define `.workspace-page`, `.workspace-hero`, `.surface-card`, form/table/state primitives, focus-visible rings, low-intensity hover feedback, gradient mesh/noise pseudo-elements and a reduced-motion media query.
- [ ] Add `.workspace-page` to DashboardView. Run `npm test -- DashboardView.test.ts`; expect PASS; commit as `feat: establish light workspace design tokens`.

### Task 4: Make dashboard the Bento reference page

**Files:** Modify `frontend/src/views/DashboardView.vue`, `frontend/src/components/DashboardCard.vue`, `AgentCard.vue`, `AgentTrace.vue`, `RiskPanel.vue`, `ChartPanel.vue`, and `frontend/src/styles/index.css`; test `DashboardView.test.ts`.

**Produces:** Hero with `data-testid="dashboard-health"`, four metric cards, agent directory, execution/risk split and charts in a responsive Bento composition while preserving endpoint use and ECharts options.

- [ ] Add a failing test asserting `[data-testid="dashboard-health"]` includes the service label.
- [ ] Run `npm test -- DashboardView.test.ts`; expect missing-testid failure.
- [ ] Implement the “今日态势” hero, health pill and `bento-metrics` wrapper. Keep all existing component props/data. Use 12px surfaces, low-contrast borders, compact hierarchy and staggered CSS variables; do not alter response transforms.
- [ ] Run `npm test -- DashboardView.test.ts`; expect PASS; commit as `feat: redesign analytics dashboard as bento workspace`.

### Task 5: Apply shared composition to every route

**Files:** Modify `frontend/src/views/LoginView.vue`, `RegisterView.vue`, `ChatView.vue`, `AdvisorWorkspaceView.vue`, `ProfileView.vue`, `RiskManagementView.vue`, `OperationsView.vue`, `AnalyticsView.vue`, `KnowledgeView.vue`; modify `frontend/src/components/EmptyState.vue`, `ErrorAlert.vue`, `LoadingPanel.vue`, `frontend/src/router/index.ts`, and global CSS; test `frontend/src/router/index.test.ts`.

**Produces:** All protected pages supply a readable route title and share page hero, toolbars, cards, table and state styles; chat retains its full-height, readable conversation layout; auth views use the same light introduction language.

- [ ] Write a failing router test requiring a non-empty `meta.title` for every `meta.requiresAuth` route.
- [ ] Run `npm test -- router/index.test.ts`; expect failure for routes without titles.
- [ ] Add Chinese titles to protected routes. Wrap each view root with `workspace-page`; keep business markup, calls and component interfaces. Replace route-specific dark backgrounds with shared classes. Add labelled text/SVG controls; ensure Empty/Error/Loading contain readable message hierarchy and `role="alert"` where applicable.
- [ ] Run `npm test -- router/index.test.ts`; expect PASS; commit as `feat: unify all workspace routes under light design`.

### Task 6: Validate the complete frontend

**Files:** Modify only scoped frontend files if validation reveals a defect.

- [ ] Run `npm test -- AppIntro.test.ts navigation.test.ts DashboardView.test.ts router/index.test.ts`; expect PASS without unhandled warnings.
- [ ] Run `npm test`; expect all Vitest suites PASS.
- [ ] Run `npm run build`; expect Vue type-check and Vite build exit 0.
- [ ] Run `npm run dev -- --host 127.0.0.1` and inspect login, dashboard, chat and a data-heavy page at 375px, 768px, 1024px and 1440px. Check no horizontal overflow, visible focus, legible tables and reduced-motion.
- [ ] Commit any scoped fixes as `fix: polish responsive workspace experience`.
