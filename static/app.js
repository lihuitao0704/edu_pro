/* ====== 智能财富管家 - 全链路测试平台 V2 ====== */
const API = location.origin;
let curAgent = 'customer';
let chatRole = '理财顾问';
let curSess = 'web-' + Math.random().toString(36).slice(2, 10);
let gChart = null;
let eChart = null;
let quizAnswers = {};  // 问卷答案 { qIndex: value }

// ====== 导航 ======
function navigate(name, el) {
  document.querySelectorAll('.ni').forEach(t => t.classList.remove('on'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('on'));
  el.classList.add('on');
  document.getElementById('pg-' + name).classList.add('on');
  if (name === 'graph') loadGraph();
  if (name === 'risk') loadAlerts();
  if (name === 'collab') loadRiskFlag();
  if (name === 'knowledge') listKnowledge();
  if (name === 'engine') { if (!eChart) eChart = echarts.init(document.getElementById('eChart')); }
}

// ====== Toast ======
function toast(msg, type = 'info') {
  const colors = { info: '#4f46e5', success: '#10b981', error: '#ef4444' };
  const el = document.createElement('div');
  el.className = 'ti';
  el.style.background = colors[type] || colors.info;
  el.textContent = msg;
  document.getElementById('toast').appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// ====== API ======
async function api(path, method = 'GET', body = null, isForm = false) {
  const opts = { method };
  if (isForm) {
    opts.body = body; // FormData
  } else if (body && method !== 'GET') {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(API + path, opts);
  return r.json();
}

function esc(s) { return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function fmtTime(ts) {
  if (!ts) return '--';
  try { return new Date(ts).toLocaleString('zh-CN', { hour12: false }); } catch(e) { return ts; }
}

// ====== Dashboard ======
async function loadDash() {
  try {
    const h = await api('/api/health');
    if (h.code === 200) { document.getElementById('lm').textContent = h.data.llm_model; }
  } catch(e) {}
  try {
    const st = await api('/api/graph/stats');
    if (st.code === 200) {
      document.getElementById('sN').textContent = st.data.node_count || 0;
      document.getElementById('sE').textContent = st.data.relationship_count || 0;
    }
  } catch(e) {}
  try {
    const pr = await api('/api/operation/product/list');
    if (pr.code === 200) {
      document.getElementById('sP').textContent = pr.data.length;
      document.getElementById('pList').innerHTML = `<table class="dt"><thead><tr><th>产品名</th><th>类型</th><th>风险</th><th>收益</th><th>起投</th></tr></thead><tbody>` +
        pr.data.map(p => `<tr><td style="font-weight:500">${p.product_name}</td><td>${p.product_type}</td><td><span class="badge ${p.risk_level <= 'R2' ? 'bg3' : p.risk_level <= 'R3' ? 'bb' : 'br'}">${p.risk_level}</span></td><td>${p.expected_return}%</td><td>${p.min_amount}元</td></tr>`).join('') +
        `</tbody></table>`;
    }
  } catch(e) {}
  checkAgents();
}

async function checkAgents() {
  const agents = [
    { name: '智能客服', icon: '🧑‍💼', path: '/api/chat/customer', body: { session_id: 'chk', message: '你好', user_id: 3 } },
    { name: '数据分析', icon: '📈', path: '/api/chat/analyst', body: { session_id: 'chk', message: '有多少客户', user_id: 2 } },
    { name: '投顾助手', icon: '🎯', path: '/api/chat/advisor', body: { session_id: 'chk', message: '推荐产品', customer_id: 3, user_id: 2 } },
    { name: '业务操作', icon: '⚡', path: '/api/chat/operator', body: { message: '查产品', session_id: 'chk', user_id: 2, user_role: '理财顾问' } },
    { name: '风控监测', icon: '⚠️', path: '/api/risk/monitor', body: { customer_id: 5, transaction_id: 'CHK', amount: 10000, transaction_type: 'cash', timestamp: '2026-07-23T10:00:00' } },
  ];
  let html = '';
  for (const a of agents) {
    let st = '⏳', stc = 'color:var(--wr)', msg = '检测中...';
    try {
      const t0 = Date.now();
      const r = await api(a.path, 'POST', a.body);
      const dt = ((Date.now() - t0) / 1000).toFixed(1);
      if (r.code === 200 || r.reply) { st = '✅'; stc = 'color:var(--ok)'; msg = dt + 's'; }
      else { st = '⚠️'; stc = 'color:var(--wr)'; msg = r.message || '异常'; }
    } catch(e) { st = '❌'; stc = 'color:var(--er)'; msg = '失败'; }
    html += `<div style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid #f1f5f9;font-size:13px">
      <span style="font-size:20px">${a.icon}</span>
      <span style="flex:1;font-weight:500">${a.name}</span>
      <span style="${stc};font-weight:600">${st}</span>
      <span style="color:var(--ts);font-size:11px">${msg}</span>
    </div>`;
  }
  document.getElementById('agentStatus').innerHTML = html;
}

// ====== Agent Config ======
const AGENTS = {
  customer: {
    name: '智能客服', icon: '🧑‍💼', badge: 'RAG 检索增强', path: '/api/chat/customer',
    body: (msg, sess) => ({ session_id: sess, message: msg, user_id: 3 }),
    hints: ['有什么年化5%以上的稳健型理财？', '资管新规对理财有什么影响？', '基金申购后多久确认？', '转人工'],
    extract: (d) => {
      let txt = d.reply || '(无回复)';
      let extra = '';
      if (d.sources && d.sources.length) {
        extra = '<div style="margin-top:8px">' + d.sources.map(s => `<span class="src">📄 ${s.title || s.source_file} (score:${(s.score || 0).toFixed(2)})</span>`).join('') + '</div>';
      }
      let meta = '';
      if (d.intent) meta = `<div class="cmm">意图: ${d.intent} | 置信度: ${d.confidence || '--'}</div>`;
      return { txt, extra, meta };
    }
  },
  advisor: {
    name: '投顾助手', icon: '🎯', badge: 'GraphRAG + 推荐', path: '/api/chat/advisor',
    body: (msg, sess) => ({ session_id: sess, message: msg, customer_id: 3, user_id: 2 }),
    hints: ['给客户推荐3款稳健型产品', '分析客户3的持仓', '客户3适合什么资产配置？'],
    extract: (d) => {
      let txt = d.reply || '(无回复)';
      let extra = '';
      const recs = d.recommendations;
      if (recs && recs.recommendations && recs.recommendations.length) {
        extra = '<div style="margin-top:8px">' + recs.recommendations.map(r => {
          const m = r.match(/product_name='([^']+)'/); const rl = r.match(/risk_level='([^']+)'/); const ret = r.match(/expected_return=([\d.]+)/); const sc = r.match(/match_score=([\d.]+)/);
          return `<div class="rec"><div class="rn">${m ? m[1] : '产品'}</div><div class="ri">${rl ? '风险: ' + rl[1] : ''} ${ret ? ' | 预期: ' + ret[1] + '%' : ''}</div>${sc ? `<div class="rs">匹配度 ${(parseFloat(sc[1]) * 100).toFixed(0)}%</div>` : ''}</div>`;
        }).join('') + '</div>';
      }
      let meta = '';
      if (d.customer_profile) meta = `<div class="cmm">画像: ${d.customer_profile.risk_level || '--'}</div>`;
      return { txt, extra, meta };
    }
  },
  analyst: {
    name: '数据分析', icon: '📈', badge: 'NL2SQL', path: '/api/chat/analyst',
    body: (msg, sess) => ({ session_id: sess, message: msg, user_id: 2 }),
    hints: ['AUM超过100万的客户有多少个？', '各产品类型的平均收益率是多少？', '最近30天的交易记录', '有多少个客户？'],
    extract: (d) => {
      let txt = d.reply || '(无回复)';
      let extra = '';
      if (d.sql) extra += `<div class="sql">${esc(d.sql)}</div>`;
      if (d.query_result && d.query_result.length) {
        const keys = Object.keys(d.query_result[0]);
        extra += `<table class="dt" style="margin-top:6px"><thead><tr>${keys.map(k => `<th>${k}</th>`).join('')}</tr></thead><tbody>` +
          d.query_result.slice(0, 10).map(row => `<tr>${keys.map(k => `<td>${row[k]}</td>`).join('')}</tr>`).join('') +
          `</tbody></table>`;
        if (d.query_result.length > 10) extra += `<div style="font-size:11px;color:var(--ts);margin-top:4px">共 ${d.query_result.length} 行，显示前 10 行</div>`;
      }
      let meta = '';
      if (d.error) meta = `<div class="cmm" style="color:var(--er)">错误: ${d.error}</div>`;
      return { txt, extra, meta };
    }
  },
  operator: {
    name: '业务操作', icon: '⚡', badge: 'NL2API + RBAC', path: '/api/chat/operator',
    body: (msg, sess) => ({ message: msg, session_id: sess, user_id: 2, user_role: chatRole }),
    hints: ['帮我查一下张三的持仓', '帮客户4申购产品2，金额500', '有哪些R3风险等级的产品？'],
    extract: (d) => {
      let txt = d.reply || '(无回复)';
      let extra = '';
      let meta = '';
      if (d.action) meta = `<div class="cmm">意图: ${d.action} | 状态: ${d.status || '--'}</div>`;
      return { txt, extra, meta };
    }
  }
};

function selAgent(id, el) {
  curAgent = id;
  document.querySelectorAll('.ai').forEach(a => a.classList.remove('on'));
  el.classList.add('on');
  const a = AGENTS[id];
  document.getElementById('chatHeader').innerHTML = `${a.icon} ${a.name} <span class="badge bb" style="margin-left:auto">${a.badge}</span>`;
  document.getElementById('cmsg').innerHTML = '';
  document.getElementById('chints').innerHTML = a.hints.map(h => `<span class="hc" onclick="sendAgentHint(this)">${h}</span>`).join('');
  curSess = 'web-' + Math.random().toString(36).slice(2, 10);
}

function sendAgentHint(el) {
  document.getElementById('cinput').value = el.textContent;
  sendAgent();
}

function addMsg(text, isUser, extra = '', meta = '') {
  const el = document.getElementById('cmsg');
  const div = document.createElement('div');
  div.className = 'cm ' + (isUser ? 'u' : 'b');
  div.innerHTML = `<div class="cma">${isUser ? '我' : AGENTS[curAgent].icon}</div><div><div class="cmb">${esc(text)}</div>${extra}${meta}</div>`;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
  return div;
}

async function sendAgent() {
  const input = document.getElementById('cinput');
  const btn = document.getElementById('csend');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  addMsg(msg, true);
  btn.disabled = true;
  btn.innerHTML = '<span class="sp" style="border-top-color:white;border-color:rgba(255,255,255,.3)"></span>';

  const botDiv = document.createElement('div');
  botDiv.className = 'cm b';
  botDiv.innerHTML = `<div class="cma">${AGENTS[curAgent].icon}</div><div><div class="cmb"><span class="sp"></span> 正在思考...</div></div>`;
  document.getElementById('cmsg').appendChild(botDiv);
  document.getElementById('cmsg').scrollTop = document.getElementById('cmsg').scrollHeight;

  try {
    const a = AGENTS[curAgent];
    const r = await api(a.path, 'POST', a.body(msg, curSess));
    const { txt, extra, meta } = a.extract(r);
    botDiv.querySelector('div:last-child').innerHTML = `<div class="cmb">${esc(txt)}</div>${extra}${meta}`;
  } catch(e) {
    botDiv.querySelector('.cmb').textContent = '请求失败: ' + e.message;
  }
  btn.disabled = false;
  btn.textContent = '发送';
  document.getElementById('cmsg').scrollTop = document.getElementById('cmsg').scrollHeight;
}

// ====== Risk Monitor ======
async function doMonitor() {
  const body = {
    customer_id: +document.getElementById('r_cid').value,
    transaction_id: document.getElementById('r_tid').value,
    amount: +document.getElementById('r_amt').value,
    transaction_type: document.getElementById('r_type').value,
    timestamp: document.getElementById('r_time').value,
  };
  const res = document.getElementById('r_result');
  res.innerHTML = '<div class="lo"><span class="sp"></span> 规则引擎匹配中...</div>';
  try {
    const r = await api('/api/risk/monitor', 'POST', body);
    if (r.code === 200) {
      const a = r.data.alert;
      const lv = a.alert_level;
      const lvMap = { low: '🔵 轻度', medium: '🟡 中度', high: '🔴 重度' };
      res.innerHTML = `<div style="border:1px solid ${lv === 'high' ? 'var(--er)' : lv === 'medium' ? 'var(--wr)' : 'var(--ok)'};border-radius:10px;padding:14px;background:${lv === 'high' ? '#fef2f2' : lv === 'medium' ? '#fffbeb' : '#f0fdf4'}">
        <div style="font-size:15px;font-weight:700" class="alert-lv ${lv}">${lvMap[lv] || lv} 预警</div>
        <table class="dt" style="margin-top:10px">
          <tr><td style="font-weight:500">触发规则</td><td>${a.trigger_rules.map(r => r.rule_id + ' ' + r.rule_name).join(', ')}</td></tr>
          <tr><td style="font-weight:500">置信度</td><td>${a.confidence}</td></tr>
          <tr><td style="font-weight:500">摘要</td><td>${a.summary}</td></tr>
          <tr><td style="font-weight:500">建议</td><td>${a.recommendation}</td></tr>
        </table>
      </div>`;
      toast('预警触发成功', 'success');
      loadAlerts();
    } else {
      res.innerHTML = `<div style="color:var(--er)">${r.message || '监测失败'}</div>`;
    }
  } catch(e) {
    res.innerHTML = `<div style="color:var(--er)">请求失败: ${e.message}</div>`;
  }
}

async function loadAlerts() {
  try {
    const r = await api('/api/risk/alerts?page_size=10');
    if (r.code === 200 && r.data.alerts) {
      const lvBadge = { low: 'bb', medium: 'by', high: 'br', '低': 'bb', '中': 'by', '高': 'br' };
      document.getElementById('alertList').innerHTML = r.data.alerts.length ?
        `<table class="dt"><thead><tr><th>ID</th><th>客户</th><th>级别</th><th>类型</th><th>状态</th></tr></thead><tbody>` +
        r.data.alerts.map(a => `<tr><td>${a.alert_id || a.id}</td><td>${a.customer_id}</td><td><span class="badge ${lvBadge[a.alert_level] || 'bb'}">${a.alert_level}</span></td><td>${a.alert_type || '--'}</td><td>${a.status}</td></tr>`).join('') +
        `</tbody></table><div style="font-size:11px;color:var(--ts);margin-top:6px">共 ${r.data.total} 条</div>`
        : '<div style="text-align:center;color:var(--ts);padding:20px">暂无预警</div>';
    }
  } catch(e) { document.getElementById('alertList').innerHTML = '<div style="color:var(--er)">加载失败</div>'; }
}

// ====== Collab ======
async function runCollab() {
  const boxes = ['eb1', 'eb2', 'eb3'];
  const arrows = ['ea1', 'ea2'];
  boxes.forEach(b => document.getElementById(b).classList.remove('active'));
  arrows.forEach(a => document.getElementById(a).classList.remove('on'));
  const res = document.getElementById('collabResult');
  res.innerHTML = '';

  document.getElementById('eb1').classList.add('active');
  res.innerHTML = '<div class="lo"><span class="sp"></span> 步骤1: 触发风控预警（大额交易15万）...</div>';
  try {
    const r = await api('/api/risk/monitor', 'POST', {
      customer_id: 5, transaction_id: 'TXN_COLLAB_' + Date.now(), amount: 150000,
      transaction_type: 'cash', timestamp: '2026-07-23T10:00:00'
    });
    if (r.code !== 200) { res.innerHTML = '<div style="color:var(--er)">风控触发失败</div>'; return; }
    const alert = r.data.alert;
    document.getElementById('ea1').classList.add('on');
    res.innerHTML = `<div class="rw ok"><span>✅</span><span class="rn2">风控预警已触发: ${alert.alert_level} 级 (${alert.trigger_rules[0].rule_name})</span></div>`;
    toast('风控预警已发布事件', 'success');
  } catch(e) { res.innerHTML = `<div style="color:var(--er)">风控触发失败: ${e.message}</div>`; return; }

  await new Promise(r => setTimeout(r, 800));
  document.getElementById('eb2').classList.add('active');
  document.getElementById('ea2').classList.add('on');
  res.innerHTML += `<div class="rw ok"><span>📡</span><span class="rn2">事件总线广播 event:risk_alert（Redis Pub/Sub）</span></div>`;

  await new Promise(r => setTimeout(r, 1500));
  document.getElementById('eb3').classList.add('active');
  await loadRiskFlag();
  res.innerHTML += `<div class="rw ok"><span>🎯</span><span class="rn2">投顾画像已更新 risk_flag（见下方表格）</span></div>`;
  toast('协作链路验证完成！', 'success');
}

async function loadRiskFlag() {
  try {
    const r = await api('/api/profile/5');
    let html = '<table class="dt"><thead><tr><th>客户ID</th><th>风险等级</th><th>风险标记(risk_flag)</th></tr></thead><tbody>';
    if (r.code === 200 && r.data) {
      html += `<tr><td>5</td><td>${r.data.risk_level || '--'}</td><td><span class="badge ${r.data.risk_flag === 'warning' ? 'by' : r.data.risk_flag === 'high' ? 'br' : 'bg3'}">${r.data.risk_flag || 'normal'}</span></td></tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('riskFlagList').innerHTML = html;
  } catch(e) {
    document.getElementById('riskFlagList').innerHTML = '<div style="color:var(--ts);font-size:13px">触发协作测试后，risk_flag 将从 normal → warning</div>';
  }
}

// ====== Graph ======
function loadGraph() {
  const cid = document.getElementById('g_cid').value;
  if (!gChart) { gChart = echarts.init(document.getElementById('gChart')); }
  if (!cid) {
    gChart.clear();
    gChart.setOption({ title: { text: '请选择客户查看图谱', left: 'center', top: 'center', textStyle: { color: '#94a3b8', fontSize: 16 } } });
    return;
  }
  const nameMap = { '3': '张三', '4': '李四', '5': '王五' };
  Promise.all([
    api('/api/graph/visualization/' + cid),
    api('/api/graph/query', 'POST', { query_type: 'customer_products', params: { customer_name: nameMap[cid] } }),
    api('/api/graph/query', 'POST', { query_type: 'industry_distribution', params: { customer_name: nameMap[cid] } }),
  ]).then(([viz, hold, ind]) => {
    if (viz.code === 200) {
      const { nodes, edges } = viz.data;
      const colorMap = { customer: '#4f46e5', product: '#10b981', industry: '#f59e0b', risk_level: '#ef4444' };
      const sizeMap = { customer: 50, product: 36, industry: 32, risk_level: 28 };
      gChart.setOption({
        tooltip: { trigger: 'item' },
        series: [{
          type: 'graph', layout: 'force',
          data: nodes.map(n => ({ id: n.id, name: n.label, symbolSize: sizeMap[n.type] || 28, itemStyle: { color: colorMap[n.type] || '#94a3b8' }, category: n.type, label: { show: true, fontSize: 10 } })),
          links: edges.map(e => ({ source: e.source, target: e.target, lineStyle: { color: '#cbd5e1' } })),
          categories: [{ name: '客户' }, { name: '产品' }, { name: '行业' }, { name: '风险等级' }],
          roam: true, draggable: true, force: { repulsion: 280, edgeLength: [80, 180] },
        }]
      }, true);
    }
    if (hold.code === 200 && hold.data && hold.data.products) {
      document.getElementById('gHold').innerHTML = `<table class="dt"><thead><tr><th>产品</th><th>风险</th><th>份额</th></tr></thead><tbody>` +
        hold.data.products.map(p => `<tr><td>${p.product_name}</td><td><span class="badge bb">${p.risk_level}</span></td><td>${p.shares}</td></tr>`).join('') + `</tbody></table>`;
    }
    if (ind.code === 200 && ind.data) {
      const inds = ind.data.industries || [];
      document.getElementById('gInd').innerHTML = inds.length ? `<table class="dt"><thead><tr><th>行业</th><th>数量</th></tr></thead><tbody>` +
        inds.map(i => `<tr><td>${i.name || i.industry_name}</td><td>${i.count || i.ratio || '--'}</td></tr>`).join('') + `</tbody></table>`
        : '<div style="text-align:center;color:var(--ts);padding:20px">暂无数据</div>';
    }
  }).catch(e => toast('图谱加载失败', 'error'));
}

// ====== Operations ======
async function op(type) {
  const bodies = {
    purchase: () => ({ customer_id: +document.getElementById('op_cid').value, product_id: +document.getElementById('op_pid').value, amount: +document.getElementById('op_amt').value, operator_id: +document.getElementById('op_oid').value }),
    redeem: () => ({ customer_id: +document.getElementById('or_cid').value, product_id: +document.getElementById('or_pid').value, shares: +document.getElementById('or_sh').value, operator_id: +document.getElementById('or_oid').value }),
    transfer: () => ({ from_customer_id: +document.getElementById('ot_from').value, to_customer_id: +document.getElementById('ot_to').value, amount: +document.getElementById('ot_amt').value, operator_id: +document.getElementById('ot_oid').value }),
    workorder: () => ({ customer_id: +document.getElementById('ow_cid').value, content: document.getElementById('ow_cont').value, order_type: document.getElementById('ow_type').value, submitter_id: +document.getElementById('ow_sid').value }),
    contact: () => ({ customer_id: +document.getElementById('oc_cid').value, field: document.getElementById('oc_field').value, value: document.getElementById('oc_val').value }),
    suspicious: () => ({ customer_id: +document.getElementById('os_cid').value, reason: document.getElementById('os_reason').value, reporter_id: +document.getElementById('os_uid').value }),
  };
  const method = (type === 'contact') ? 'PUT' : 'POST';
  try {
    const r = await api('/api/operation/' + type, method, bodies[type]());
    toast(r.message || '操作完成', r.code === 200 ? 'success' : 'error');
  } catch(e) { toast('操作失败: ' + e.message, 'error'); }
}

// ====== NL2API ======
function setRole(el, role) {
  chatRole = role;
  document.querySelectorAll('#roleChips .badge').forEach(b => b.style.opacity = '0.5');
  el.style.opacity = '1';
}

function sendHint(el) {
  document.getElementById('ninput').value = el.textContent;
  sendNL2API();
}

async function sendNL2API() {
  const input = document.getElementById('ninput');
  const btn = document.getElementById('nsend');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  const el = document.getElementById('nmsg');
  el.innerHTML += `<div class="cm u"><div class="cma">我</div><div><div class="cmb">${esc(msg)}</div></div></div>`;
  el.scrollTop = el.scrollHeight;
  btn.disabled = true;
  const botDiv = document.createElement('div');
  botDiv.className = 'cm b';
  botDiv.innerHTML = `<div class="cma">AI</div><div><div class="cmb"><span class="sp"></span> 正在分析...</div></div>`;
  el.appendChild(botDiv);
  el.scrollTop = el.scrollHeight;
  try {
    const r = await api('/api/chat/operator', 'POST', { message: msg, session_id: 'nl2api-' + Date.now(), user_id: 2, user_role: chatRole });
    let meta = '';
    if (r.action) meta = `<div class="cmm">意图: ${r.action} | 状态: ${r.status || '--'}</div>`;
    botDiv.querySelector('div:last-child').innerHTML = `<div class="cmb">${esc(r.reply || '(无回复)')}</div>${meta}`;
  } catch(e) {
    botDiv.querySelector('.cmb').textContent = '请求失败: ' + e.message;
  }
  btn.disabled = false;
  el.scrollTop = el.scrollHeight;
}

// ====== Knowledge Base ======
async function uploadKnowledge() {
  const fileInput = document.getElementById('k_file');
  if (!fileInput.files.length) { toast('请选择文件', 'error'); return; }
  const fd = new FormData();
  fd.append('file', fileInput.files[0]);
  fd.append('knowledge_type', document.getElementById('k_type').value);
  const title = document.getElementById('k_title').value.trim();
  if (title) fd.append('title', title);

  const res = document.getElementById('k_up_result');
  res.innerHTML = '<div class="lo"><span class="sp"></span> 上传中...</div>';
  try {
    const r = await api('/api/knowledge/upload', 'POST', fd, true);
    if (r.code === 200) {
      res.innerHTML = `<div class="rw ok"><span>✅</span><span class="rn2">上传成功</span></div>`;
      toast('知识文档上传成功', 'success');
      listKnowledge();
    } else {
      res.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">${r.message || '上传失败'}</span></div>`;
    }
  } catch(e) {
    res.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">上传失败: ${e.message}</span></div>`;
  }
}

async function listKnowledge() {
  const el = document.getElementById('k_list');
  el.innerHTML = '<div class="lo"><span class="sp"></span> 加载中...</div>';
  try {
    const r = await api('/api/knowledge/list?page=1&size=20');
    if (r.code === 200 && r.data.items) {
      const items = r.data.items;
      el.innerHTML = items.length ? `<table class="dt"><thead><tr><th>ID</th><th>标题</th><th>类型</th><th>状态</th><th>创建时间</th></tr></thead><tbody>` +
        items.map(k => `<tr><td>${k.id}</td><td>${esc(k.title || k.file_name || '--')}</td><td><span class="badge bb">${k.knowledge_type || '--'}</span></td><td>${k.status || '--'}</td><td>${fmtTime(k.created_at)}</td></tr>`).join('') +
        `</tbody></table><div style="font-size:11px;color:var(--ts);margin-top:6px">共 ${r.data.total} 条</div>`
        : '<div style="text-align:center;color:var(--ts);padding:20px">暂无知识文档</div>';
    } else {
      el.innerHTML = `<div style="color:var(--er)">${r.message || '加载失败'}</div>`;
    }
  } catch(e) { el.innerHTML = '<div style="color:var(--er)">加载失败</div>'; }
}

async function searchKnowledge() {
  const query = document.getElementById('k_query').value.trim();
  if (!query) { toast('请输入检索关键词', 'error'); return; }
  const el = document.getElementById('k_search_result');
  el.innerHTML = '<div class="lo"><span class="sp"></span> 检索中...</div>';
  try {
    const fd = new FormData();
    fd.append('query', query);
    fd.append('top_k', '5');
    const r = await api('/api/knowledge/search', 'POST', fd, true);
    if (r.code === 200 && r.data.results) {
      const results = r.data.results;
      el.innerHTML = results.length ? `<div style="font-size:12px;color:var(--ts);margin-bottom:8px">找到 ${results.length} 条相关结果</div>` +
        results.map((r, i) => `<div class="rec" style="margin-bottom:8px"><div class="rn">结果 ${i+1} <span class="rs">score: ${(r.score || 0).toFixed(3)}</span></div><div class="ri" style="white-space:pre-wrap;font-family:inherit;font-size:12px">${esc(r.content || r.text || r.title || JSON.stringify(r))}</div></div>`).join('')
        : '<div style="text-align:center;color:var(--ts);padding:20px">无匹配结果</div>';
    } else {
      el.innerHTML = `<div style="color:var(--er)">${r.message || '检索失败'}</div>`;
    }
  } catch(e) { el.innerHTML = `<div style="color:var(--er)">检索失败: ${e.message}</div>`; }
}

// ====== Profile ======
async function getProfile() {
  const cid = document.getElementById('p_cid').value;
  const el = document.getElementById('p_view');
  el.innerHTML = '<div class="lo"><span class="sp"></span> 加载中...</div>';
  try {
    const r = await api('/api/profile/' + cid);
    if (r.code === 200 && r.data) {
      const d = r.data;
      const scoreBadge = (s) => {
        const v = parseFloat(s);
        if (isNaN(v)) return '--';
        return v >= 70 ? `<span class="badge bg3">${s}</span>` : v >= 40 ? `<span class="badge by">${s}</span>` : `<span class="badge br">${s}</span>`;
      };
      el.innerHTML = `<table class="dt">
        <tr><td>客户ID</td><td>${d.customer_id}</td></tr>
        <tr><td>风险等级</td><td><span class="badge bpp">${d.risk_level || '--'}</span></td></tr>
        <tr><td>风险总分</td><td>${scoreBadge(d.risk_score)}</td></tr>
        <tr><td>基础得分</td><td>${scoreBadge(d.basic_score)}</td></tr>
        <tr><td>经验得分</td><td>${scoreBadge(d.experience_score)}</td></tr>
        <tr><td>风险偏好</td><td>${scoreBadge(d.risk_pref_score)}</td></tr>
        <tr><td>行为得分</td><td>${scoreBadge(d.behavior_score)}</td></tr>
        <tr><td>置信度</td><td>${d.confidence_score || '--'}</td></tr>
        <tr><td>总资产</td><td>${d.total_assets ? parseFloat(d.total_assets).toLocaleString() + ' 元' : '--'}</td></tr>
        <tr><td>年收入</td><td>${d.annual_income_range || '--'}</td></tr>
        <tr><td>投资经验</td><td>${d.investment_experience || '--'}</td></tr>
        <tr><td>更新时间</td><td>${fmtTime(d.update_time)}</td></tr>
      </table>`;
    } else {
      el.innerHTML = `<div style="color:var(--er)">${r.message || '查询失败'}</div>`;
    }
  } catch(e) { el.innerHTML = `<div style="color:var(--er)">请求失败: ${e.message}</div>`; }
}

async function updateProfile() {
  const cid = document.getElementById('p_uc_id').value;
  const tagsStr = document.getElementById('p_uc_tag').value.trim();
  const el = document.getElementById('p_up_result');
  if (!tagsStr) { toast('请输入标签JSON', 'error'); return; }
  let tags;
  try { tags = JSON.parse(tagsStr); } catch(e) { toast('标签格式错误，需为JSON对象', 'error'); return; }

  el.innerHTML = '<div class="lo"><span class="sp"></span> 更新中...</div>';
  try {
    const r = await api('/api/profile/' + cid, 'PUT', { tags });
    if (r.code === 200) {
      el.innerHTML = `<div class="rw ok"><span>✅</span><span class="rn2">更新成功: 已更新 ${r.data?.updated_tags ?? 0} 个标签</span></div>`;
      toast('画像标签更新成功', 'success');
    } else {
      el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">${r.message || '更新失败'}</span></div>`;
    }
  } catch(e) { el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">请求失败: ${e.message}</span></div>`; }
}

async function assessProfile() {
  const cid = document.getElementById('p_a_cid').value;
  const el = document.getElementById('p_assess_result');
  el.innerHTML = '<div class="lo"><span class="sp"></span> 引擎研判中（四维度打分 + 熔断检查）...</div>';
  try {
    const r = await api('/api/profile/' + cid + '/assess', 'POST', { trigger_type: 'manual' });
    if (r.code === 200 && r.data) {
      const d = r.data;
      const dims = d.dimensions || {};
      el.innerHTML = `<div style="font-size:13px;font-weight:600;margin-bottom:10px">研判结果 <span class="badge bpp">${d.risk_level || '--'}</span></div>
        <table class="dt"><thead><tr><th>维度</th><th>得分</th><th>权重</th><th>加权分</th></tr></thead><tbody>
          ${Object.entries(dims).map(([k,v]) => `<tr><td>${k}</td><td>${v.score ?? v.value ?? '--'}</td><td>${v.weight || '--'}</td><td>${v.weighted_score ?? '--'}</td></tr>`).join('')}
        </tbody></table>
        ${d.circuit_breaker ? `<div style="margin-top:10px;font-size:12px;padding:8px 12px;border-radius:8px;background:${d.circuit_breaker.passed ? '#f0fdf4' : '#fef2f2'};border-left:3px solid ${d.circuit_breaker.passed ? 'var(--ok)' : 'var(--er)'}">熔断: ${d.circuit_breaker.passed ? '✅ 通过' : '❌ 触发'} — ${d.circuit_breaker.reason || ''}</div>` : ''}
        ${d.score != null ? `<div style="margin-top:6px;font-size:12px;color:var(--ts)">总分: ${d.score}</div>` : ''}`;
      toast('画像研判完成', 'success');
    } else {
      el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">${r.message || '研判失败'}</span></div>`;
    }
  } catch(e) { el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">请求失败: ${e.message}</span></div>`; }
}

// ====== Risk Assessment Page ======
async function loadQuestionnaire() {
  const el = document.getElementById('rq_list');
  el.innerHTML = '<div class="lo"><span class="sp"></span> 加载问卷中...</div>';
  try {
    const r = await api('/api/risk/questionnaire');
    if (r.code === 200 && r.data) {
      quizAnswers = {};
      el.innerHTML = r.data.map((q, i) => {
        const optsHtml = q.options.map((opt, oi) => `<label style="display:flex;align-items:center;gap:6px;padding:4px 0;cursor:pointer;font-size:12px"><input type="radio" name="q_${i}" value="${oi}" onchange="quizAnswers[${i}]=${oi};updateAnsCount()"> ${esc(opt.text || opt)}</label>`).join('');
        return `<div style="padding:12px 0;border-bottom:1px solid #f1f5f9"><div style="font-size:13px;font-weight:500;margin-bottom:6px">${i+1}. ${esc(q.question || q.title || q.text)}</div><div style="padding-left:8px">${optsHtml}</div></div>`;
      }).join('');
      updateAnsCount();
    } else {
      el.innerHTML = `<div style="color:var(--er)">${r.message || '加载失败'}</div>`;
    }
  } catch(e) { el.innerHTML = `<div style="color:var(--er)">请求失败: ${e.message}</div>`; }
}

function updateAnsCount() {
  const cnt = Object.keys(quizAnswers).length;
  document.getElementById('rq_ans_count').textContent = `已答 ${cnt} 题`;
}

async function submitAssessment() {
  const cid = +document.getElementById('rq_cid').value;
  const el = document.getElementById('rq_result');
  if (Object.keys(quizAnswers).length === 0) { toast('请先获取并填写问卷', 'error'); return; }
  // 答案按题号顺序排列
  const maxIdx = Math.max(...Object.keys(quizAnswers).map(Number));
  const answers = [];
  for (let i = 0; i <= maxIdx; i++) { answers.push(quizAnswers[i] ?? 0); }

  el.innerHTML = '<div class="lo"><span class="sp"></span> 评分中...</div>';
  try {
    const r = await api('/api/risk/assessment', 'POST', { customer_id: cid, answers });
    if (r.code === 200 && r.data) {
      el.innerHTML = `<div class="rw ok"><span>✅</span><span class="rn2">风评完成 — 等级: <span class="badge bpp" style="font-size:14px">${r.data.risk_level}</span> | 总分: ${r.data.total_score ?? r.data.score ?? '--'}</span></div>`;
      toast('风评完成: ' + r.data.risk_level, 'success');
    } else {
      el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">${r.message || '提交失败'}</span></div>`;
    }
  } catch(e) { el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">请求失败: ${e.message}</span></div>`; }
}

async function checkSuitability() {
  const cid = +document.getElementById('rq_sc_cid').value;
  const code = document.getElementById('rq_sc_code').value.trim();
  const el = document.getElementById('rq_sc_result');
  if (!code) { toast('请输入产品代码', 'error'); return; }
  el.innerHTML = '<div class="lo"><span class="sp"></span> 校验中...</div>';
  try {
    const r = await api('/api/risk/suitability-check', 'POST', { customer_id: cid, product_code: code });
    if (r.code === 200 && r.data) {
      const d = r.data;
      el.innerHTML = `<div class="rw ok"><span>✅</span><span class="rn2">匹配通过 — ${d.warning || '客户风险等级与产品匹配'}</span></div>`;
      toast('适当性匹配通过', 'success');
    } else if (r.code === 403) {
      el.innerHTML = `<div class="rw fl"><span>⚠️</span><span class="rn2">不匹配 — ${r.message} ${r.data?.warning ? '| ' + r.data.warning : ''}</span></div>`;
    } else {
      el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">${r.message || '校验失败'}</span></div>`;
    }
  } catch(e) { el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">请求失败: ${e.message}</span></div>`; }
}

// ====== Alert Handle Page ======
async function getAlertDetail() {
  const id = document.getElementById('a_id').value.trim();
  const el = document.getElementById('a_detail');
  if (!id) { toast('请输入预警ID', 'error'); return; }
  el.innerHTML = '<div class="lo"><span class="sp"></span> 查询中...</div>';
  try {
    const r = await api('/api/risk/alert/' + id);
    if (r.code === 200 && r.data) {
      const d = r.data;
      const lv = d.alert_level;
      el.innerHTML = `<div style="border:1px solid ${lv === 'high' ? 'var(--er)' : lv === 'medium' ? 'var(--wr)' : 'var(--ok)'};border-radius:10px;padding:14px;background:${lv === 'high' ? '#fef2f2' : lv === 'medium' ? '#fffbeb' : '#f0fdf4'}">
        <div style="font-size:14px;font-weight:700" class="alert-lv ${lv}">${lv?.toUpperCase()} 预警详情</div>
        <table class="dt" style="margin-top:10px">
          <tr><td>预警ID</td><td>${d.alert_id || d.id}</td></tr>
          <tr><td>客户ID</td><td>${d.customer_id}</td></tr>
          <tr><td>类型</td><td>${d.alert_type || '--'}</td></tr>
          <tr><td>级别</td><td><span class="badge ${lv === 'high' ? 'br' : lv === 'medium' ? 'by' : 'bb'}">${d.alert_level}</span></td></tr>
          <tr><td>状态</td><td><span class="badge ${d.status === '待处理' ? 'by' : 'bg3'}">${d.status}</span></td></tr>
          <tr><td>置信度</td><td>${d.confidence || '--'}</td></tr>
          <tr><td>触发规则</td><td>${(d.trigger_detail || d.trigger_rules || []).toString()}</td></tr>
          <tr><td>摘要</td><td>${d.summary || '--'}</td></tr>
          <tr><td>建议</td><td>${d.recommendation || '--'}</td></tr>
          <tr><td>创建时间</td><td>${fmtTime(d.created_at)}</td></tr>
        </table>
      </div>`;
    } else {
      el.innerHTML = `<div style="color:var(--er)">${r.message || '查询失败'}</div>`;
    }
  } catch(e) { el.innerHTML = `<div style="color:var(--er)">请求失败: ${e.message}</div>`; }
}

async function handleAlert() {
  const id = document.getElementById('a_h_id').value.trim();
  const action = document.getElementById('a_h_action').value;
  const uid = +document.getElementById('a_h_uid').value;
  const note = document.getElementById('a_h_note').value.trim();
  const el = document.getElementById('a_h_result');
  if (!id) { toast('请输入预警ID', 'error'); return; }
  el.innerHTML = '<div class="lo"><span class="sp"></span> 提交中...</div>';
  try {
    const r = await api('/api/risk/alert/' + id + '/handle', 'PUT', { action, handler_id: uid, handle_note: note });
    if (r.code === 200) {
      el.innerHTML = `<div class="rw ok"><span>✅</span><span class="rn2">处理成功 — 状态更新为: ${action}</span></div>`;
      toast('预警已处理', 'success');
    } else {
      el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">${r.message || '处理失败'}</span></div>`;
    }
  } catch(e) { el.innerHTML = `<div class="rw fl"><span>❌</span><span class="rn2">请求失败: ${e.message}</span></div>`; }
}

// ====== Engine Test Page ======
async function runEngineTest() {
  const chartEl = document.getElementById('eChart');
  const textEl = document.getElementById('e_text');
  if (!eChart) eChart = echarts.init(chartEl);
  eChart.showLoading({ color: '#4f46e5' });
  textEl.innerHTML = '<div class="lo"><span class="sp"></span> 引擎运行中...</div>';

  try {
    const r = await api('/api/engine/test');
    eChart.hideLoading();
    if (r.code === 200 && r.data) {
      const d = r.data;
      const profile = d.customer_profile || {};
      const dims = profile.dimensions || {};

      // ECharts bar chart for dimensions
      const dimNames = { basic: '基础', experience: '经验', risk_pref: '风险偏好', behavior: '行为' };
      const dimKeys = Object.keys(dims);
      eChart.setOption({
        title: { text: '四维度得分', left: 'center', textStyle: { fontSize: 14, color: '#64748b' } },
        tooltip: { trigger: 'axis' },
        grid: { left: 60, right: 30, top: 50, bottom: 30 },
        xAxis: { type: 'value', max: 100, axisLabel: { fontSize: 10 } },
        yAxis: { type: 'category', data: dimKeys.map(k => dimNames[k] || k), axisLabel: { fontSize: 11 } },
        series: [{
          type: 'bar',
          data: dimKeys.map(k => dims[k]?.score ?? dims[k]?.value ?? 0),
          itemStyle: { color: p => p.dataValue >= 70 ? '#10b981' : p.dataValue >= 40 ? '#f59e0b' : '#ef4444', borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: 'right', fontSize: 11 }
        }]
      }, true);

      // Text summary
      const cb = d.circuit_breaker || {};
      const conf = d.confidence || {};
      textEl.innerHTML = `
        <div style="padding:16px">
          <div style="font-size:16px;font-weight:700;margin-bottom:12px">风险等级: <span class="badge bpp" style="font-size:16px">${profile.risk_level || '--'} <span style="font-weight:400;font-size:12px">${profile.risk_name || ''}</span></span></div>
          <table class="dt">
            <tr><td>总分</td><td style="font-size:18px;font-weight:700;color:var(--p)">${profile.total_score ?? '--'}</td></tr>
            <tr><td>基础</td><td>${dims.basic?.score ?? '--'}</td></tr>
            <tr><td>经验</td><td>${dims.experience?.score ?? '--'}</td></tr>
            <tr><td>风险偏好</td><td>${dims.risk_pref?.score ?? '--'}</td></tr>
            <tr><td>行为</td><td>${dims.behavior?.score ?? '--'}</td></tr>
          </table>
          <div style="margin-top:12px;padding:10px 14px;border-radius:8px;background:${cb.passed !== false ? '#f0fdf4' : '#fef2f2'};border-left:3px solid ${cb.passed !== false ? 'var(--ok)' : 'var(--er)'};font-size:12px">
            熔断检查: ${cb.passed !== false ? '✅ 通过' : '❌ 触发'} ${cb.warnings?.length ? ' — ' + cb.warnings.join('; ') : ''}
          </div>
          <div style="margin-top:8px;font-size:12px;color:var(--ts)">置信度: ${typeof conf === 'object' ? JSON.stringify(conf) : conf}</div>
          <div style="margin-top:4px;font-size:11px;color:var(--ts)">状态: ${d.status || 'OK'}</div>
        </div>`;
      toast('引擎自测完成', 'success');
    } else {
      textEl.innerHTML = `<div style="color:var(--er)">${r.message || '自测失败'}</div>`;
    }
  } catch(e) {
    eChart.hideLoading();
    textEl.innerHTML = `<div style="color:var(--er)">请求失败: ${e.message}</div>`;
  }
}

// ====== Tests (Enhanced — 25 cases) ======
const TESTS = [
  // Agent 接口 (5)
  { g:'agent', name:'智能客服', icon:'🧑‍💼', path:'/api/chat/customer', m:'POST', body:{ session_id:'t', message:'你好', user_id:3 } },
  { g:'agent', name:'数据分析', icon:'📈', path:'/api/chat/analyst', m:'POST', body:{ session_id:'t', message:'有多少客户', user_id:2 } },
  { g:'agent', name:'投顾助手', icon:'🎯', path:'/api/chat/advisor', m:'POST', body:{ session_id:'t', message:'推荐产品', customer_id:3, user_id:2 } },
  { g:'agent', name:'业务操作', icon:'⚡', path:'/api/chat/operator', m:'POST', body:{ message:'查产品', session_id:'t', user_id:2, user_role:'理财顾问' } },
  { g:'agent', name:'风控监测', icon:'⚠️', path:'/api/risk/monitor', m:'POST', body:{ customer_id:5, transaction_id:'TST', amount:10000, transaction_type:'cash', timestamp:'2026-07-23T10:00:00' } },
  // 基础 & 引擎 (3)
  { g:'ops', name:'健康检查', icon:'💚', path:'/api/health', m:'GET' },
  { g:'ops', name:'引擎自测', icon:'⚙️', path:'/api/engine/test', m:'GET' },
  { g:'ops', name:'图谱统计', icon:'📊', path:'/api/graph/stats', m:'GET' },
  // 画像 & 风评 (4)
  { g:'ops', name:'客户画像查询', icon:'👤', path:'/api/profile/3', m:'GET' },
  { g:'ops', name:'画像标签更新', icon:'✏️', path:'/api/profile/3', m:'PUT', body:{ tags:{ vip:true } } },
  { g:'ops', name:'风评问卷', icon:'📝', path:'/api/risk/questionnaire', m:'GET' },
  { g:'ops', name:'适当性校验', icon:'🎯', path:'/api/risk/suitability-check', m:'POST', body:{ customer_id:3, product_code:'F000001' } },
  // 知识库 (3)
  { g:'ops', name:'知识列表', icon:'📚', path:'/api/knowledge/list', m:'GET' },
  { g:'ops', name:'知识检索', icon:'🔍', path:'/api/knowledge/search', m:'FORM', body:{ query:'理财产品', top_k:3 } },
  { g:'ops', name:'知识库上传', icon:'📤', path:'/api/knowledge/upload', m:'SKIP' },  // 需文件，跳过自动化
  // 业务操作 (6)
  { g:'ops', name:'产品列表', icon:'📋', path:'/api/operation/product/list', m:'GET' },
  { g:'ops', name:'产品筛选(R3)', icon:'🔎', path:'/api/operation/product/list?risk_level=R3', m:'GET' },
  { g:'ops', name:'图谱可视化', icon:'🔗', path:'/api/graph/visualization/3', m:'GET' },
  { g:'ops', name:'预警列表', icon:'📋', path:'/api/risk/alerts', m:'GET' },
  { g:'ops', name:'联系信息更新', icon:'📞', path:'/api/operation/contact', m:'PUT', body:{ customer_id:3, field:'phone', value:'13800138000' } },
  { g:'ops', name:'可疑上报', icon:'🚨', path:'/api/operation/suspicious', m:'POST', body:{ customer_id:5, reason:'测试：大额异常转账', reporter_id:1 } },
  // 投顾扩展 (3)
  { g:'ops', name:'纯推荐接口', icon:'🎁', path:'/api/chat/recommend', m:'POST', body:{ customer_id:3 } },
  { g:'ops', name:'资产配置', icon:'💼', path:'/api/chat/allocation', m:'POST', body:{ customer_id:3 } },
  { g:'ops', name:'画像风控', icon:'🛡️', path:'/api/risk/profile/5', m:'GET' },
];

let lastResponses = {}; // 保存最后一次响应详情

function renderTests() {
  document.getElementById('tAgent').innerHTML = TESTS.filter(t=>t.g==='agent').map((t,i)=>tcHtml(t,'a'+i)).join('');
  document.getElementById('tOps').innerHTML = TESTS.filter(t=>t.g==='ops').map((t,i)=>tcHtml(t,'o'+i)).join('');
  document.getElementById('t_cnt_label').textContent = `${TESTS.filter(t=>t.m!=='SKIP').length} 项可测`;
}

function tcHtml(t, idx) {
  const skip = t.m === 'SKIP';
  return `<div class="tc" id="tc-${idx}" onclick="${skip ? '' : `runTest('${idx}')`}">
    <div class="tiv" style="background:var(--pb);color:var(--p)">${t.icon}</div>
    <div class="tin"><div class="tn">${t.name}</div><div class="td">${t.m} ${t.path}</div></div>
    <div class="tst" id="ts-${idx}">${skip ? '⏭' : '○'}</div>
  </div>`;
}

let tPass=0, tFail=0, tSkip=0;

async function runTest(idx) {
  const t = TESTS[idx];
  if (!t || t.m === 'SKIP') return;
  const card = document.getElementById('tc-'+idx);
  const status = document.getElementById('ts-'+idx);
  card.classList.add('rn');
  status.innerHTML = '<span class="sp"></span>';
  try {
    const t0 = performance.now();
    let r;
    if (t.m === 'FORM') {
      const fd = new FormData();
      Object.entries(t.body).forEach(([k,v]) => fd.append(k, v));
      r = await api(t.path, 'POST', fd, true);
    } else {
      r = await api(t.path, t.m, t.body);
    }
    const ms = Math.round(performance.now() - t0);
    lastResponses[idx] = { ...r, _ms: ms, _path: t.path, _method: t.m };
    const ok = r.code === 200 || r.reply || r.data;
    status.textContent = ok ? '✅' : '❌';
    card.classList.remove('rn');
    addResult(t.name, ok, `${ms}ms`, idx);
    if (ok) tPass++; else tFail++;
  } catch(e) {
    status.textContent = '❌';
    card.classList.remove('rn');
    addResult(t.name, false, 'Error', idx);
    tFail++;
  }
  updTest();
}

async function runAllTests() {
  tPass=0; tFail=0; tSkip=0;
  document.getElementById('tResults').innerHTML = '';
  updTest();
  for (let i=0; i<TESTS.length; i++) {
    const t = TESTS[i];
    if (t.m === 'SKIP') { tSkip++; continue; }
    const card = document.getElementById('tc-'+i);
    const status = document.getElementById('ts-'+i);
    card.classList.remove('rn');
    status.textContent = '○';
    card.classList.add('rn');
    status.innerHTML = '<span class="sp"></span>';
    try {
      const t0 = performance.now();
      let r;
      if (t.m === 'FORM') {
        const fd = new FormData();
        Object.entries(t.body).forEach(([k,v]) => fd.append(k, v));
        r = await api(t.path, 'POST', fd, true);
      } else {
        r = await api(t.path, t.m, t.body);
      }
      const ms = Math.round(performance.now() - t0);
      lastResponses[i] = { ...r, _ms: ms, _path: t.path, _method: t.m };
      const ok = r.code === 200 || r.reply || r.data;
      status.textContent = ok ? '✅' : '❌';
      addResult(t.name, ok, `${ms}ms`, i);
      if (ok) tPass++; else tFail++;
    } catch(e) {
      status.textContent = '❌';
      addResult(t.name, false, 'Error', i);
      tFail++;
    }
    card.classList.remove('rn');
    updTest();
    await new Promise(r => setTimeout(r, 150));
  }
}

function addResult(name, ok, ms, idx) {
  const el = document.getElementById('tResults');
  const div = document.createElement('div');
  div.className = 'rw ' + (ok ? 'ok' : 'fl');
  div.innerHTML = `<span>${ok?'✅':'❌'}</span><span class="rn2">${name}</span><span class="rm">${ms}</span>
    <button class="btn bo bs" style="margin-left:auto;padding:2px 8px;font-size:11px" onclick="showDetail(${idx})">详情</button>`;
  el.insertBefore(div, el.firstChild);
}

function showDetail(idx) {
  const r = lastResponses[idx];
  if (!r) { toast('无响应数据', 'error'); return; }
  const t = TESTS[idx];
  const win = window.open('', '_blank', 'width=700,height=600');
  win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>响应详情 - ${t.name}</title>
    <style>body{font-family:monospace;font-size:12px;padding:20px;background:#0d1117;color:#c9d1d9;white-space:pre-wrap;word-break:break-all}
    .h{color:#7ee7c8}.k{color:#79c0ff}.s{color:#a5d6ff}.n{color:#ffa657}.b{color:#ff7b72}</style></head>
    <body><div style="color:#58a6ff;margin-bottom:10px;font-size:14px;font-weight:700">${t.m} ${t.path} — ${r._ms}ms</div>
    <div>${syntaxHighlight(r)}</div></body></html>`);
}

function syntaxHighlight(obj) {
  const json = JSON.stringify(obj, null, 2);
  return json
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/(".*?")\s*:/g, '<span class="k">$1</span>:')
    .replace(/: (".*?")/g, ': <span class="s">$1</span>')
    .replace(/\b(true|false)\b/g, '<span class="b">$1</span>')
    .replace(/\b(null)\b/g, '<span class="n">$1</span>')
    .replace(/\b(\d+\.?\d*)\b/g, '<span class="n">$1</span>')
    .replace(/\n/g, '<br>').replace(/  /g, '&nbsp;&nbsp;');
}

function updTest() {
  document.getElementById('tSum').style.display = 'flex';
  document.getElementById('tTotal').textContent = tPass + tFail + tSkip;
  document.getElementById('tPass').textContent = tPass;
  document.getElementById('tFail').textContent = tFail;
}

// ====== Init ======
document.addEventListener('DOMContentLoaded', () => {
  loadDash();
  renderTests();
  selAgent('customer', document.querySelector('.ai.on'));
});