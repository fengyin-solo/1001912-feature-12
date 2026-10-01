<template>
  <section class="page" data-module="collector">
    <header class="page-head">
      <div>
        <h2>集电线路管理</h2>
        <p class="page-desc">按线路所属班组收口：本班组只能提交本班组线路的巡视结果与缺陷登记，跨班组线路只读；停运申请由责任人提交并写明原因。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出集电线路清单</button>
      </div>
    </header>

    <div class="identity-bar">
      <span class="identity-title">当前登录身份：</span>
      <label class="identity-item">
        <span>所属班组</span>
        <select v-model="team" @change="onTeamChange">
          <option v-for="name in teamNames" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label class="identity-item">
        <span>操作人</span>
        <select v-model="operator" @change="onOperatorChange">
          <option v-for="name in teams[team] ?? []" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <span class="identity-hint">本班组可提交；别的班组线路只能查看，停运线路全员只读。</span>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>线路编号</span>
        <input v-model="keyword" placeholder="按线路编号检索" />
      </label>
      <label class="filter-item">
        <span>线路状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table collector-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-readonly': row.只读 && !row.归属本班组, 'row-stopped': row.status === '已停运' }">
          <td v-for="column in columns" :key="column" :title="column === '线路状态' && row.停运原因 ? `停运原因：${row.停运原因}` : ''">
            <template v-if="column === '所属班组'">
              {{ row[column] }}
              <span v-if="row.归属本班组" class="tag tag-self">本班组</span>
              <span v-else class="tag tag-other">仅查看</span>
            </template>
            <template v-else-if="column === '线路状态'">
              {{ row[column] }}
              <span v-if="row.status === '已停运'" class="tag tag-stop">只读</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <template v-if="!row.只读">
              <button class="link" type="button" @click="openAction('提交巡视', row)">提交巡视</button>
              <button class="link" type="button" @click="openAction('登记缺陷', row)">登记缺陷</button>
              <button
                v-if="row.可申请停运"
                class="link link-danger"
                type="button"
                @click="openAction('停运线路', row)"
              >
                申请停运
              </button>
              <button class="link" type="button" @click="openAction('变更责任人', row)">变更责任人</button>
            </template>
            <template v-else>
              <span class="readonly-text">
                {{ row.status === '已停运' ? '线路已停运，只读' : `归属${row.所属班组}，仅查看` }}
              </span>
            </template>
            <button class="link link-detail" type="button" @click="openDetail(row)">明细</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无集电线路数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条集电线路记录；待巡视线段 {{ stats[2]?.value ?? 0 }} 条（与运营概览同口径）</span>
      <span v-if="feedback" :class="feedbackOk ? 'success-text' : 'error-text'">{{ feedback }}</span>
    </footer>

    <!-- 动作弹窗 -->
    <div v-if="dialog" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialog.action }}｜{{ dialog.row.线路编号 }}</h3>
        <p class="modal-sub">
          归属：{{ dialog.row.所属班组 }} / {{ dialog.row.责任人 }}
          <template v-if="dialog.action === '停运线路'">（仅限责任人本人申请）</template>
        </p>

        <template v-if="dialog.action === '提交巡视'">
          <label class="form-item">
            <span>巡视结论 <em>*</em></span>
            <select v-model="form.巡视结论">
              <option value="" disabled>请选择巡视结论</option>
              <option value="运行正常">运行正常</option>
              <option value="存在缺陷">存在缺陷</option>
            </select>
          </label>
          <label class="form-item">
            <span>巡视日期</span>
            <input v-model="form.巡视日期" type="date" />
          </label>
          <label class="form-item">
            <span>巡视说明</span>
            <textarea v-model="form.巡视说明" rows="3" placeholder="通道、杆塔、绝缘子等巡视情况"></textarea>
          </label>
        </template>

        <template v-else-if="dialog.action === '登记缺陷'">
          <label class="form-item">
            <span>缺陷描述 <em>*</em></span>
            <textarea v-model="form.缺陷描述" rows="3" placeholder="写明缺陷部位与现象，例如 N18 绝缘子破损"></textarea>
          </label>
          <label class="form-item">
            <span>发现日期</span>
            <input v-model="form.发现日期" type="date" />
          </label>
        </template>

        <template v-else-if="dialog.action === '停运线路'">
          <label class="form-item">
            <span>停运原因 <em>*</em></span>
            <textarea v-model="form.停运原因" rows="3" placeholder="申请停运必须写明停运原因"></textarea>
          </label>
          <label class="form-item">
            <span>停运日期</span>
            <input v-model="form.停运日期" type="date" />
          </label>
        </template>

        <template v-else-if="dialog.action === '变更责任人'">
          <label class="form-item">
            <span>转入班组 <em>*</em></span>
            <select v-model="form.新班组">
              <option v-for="name in teamNames" :key="name" :value="name">{{ name }}</option>
            </select>
          </label>
          <label class="form-item">
            <span>新责任人 <em>*</em></span>
            <select v-model="form.新责任人">
              <option v-for="name in teams[form.新班组] ?? []" :key="name" :value="name">{{ name }}</option>
            </select>
          </label>
          <p class="modal-tip">变更后线路按新班组收口；历史巡视记录仍归原班组，不会被改写。</p>
        </template>

        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAction">
            {{ submitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 明细弹窗 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal modal-wide">
        <h3>线路明细｜{{ detail.线路编号 }}</h3>
        <table class="data-table detail-table">
          <tbody>
            <tr><th>所属班组 / 责任人</th><td>{{ detail.所属班组 }} / {{ detail.责任人 }}</td>
                <th>线路状态</th><td>{{ detail.线路状态 }}</td></tr>
            <tr><th>起止杆塔</th><td>{{ detail.起止杆塔 }}</td>
                <th>线路长度</th><td>{{ detail.线路长度 }}</td></tr>
            <tr><th>上次巡视日</th><td>{{ detail.上次巡视日 ?? '—' }}</td>
                <th>缺陷数量</th><td>{{ detail.缺陷数量 }}</td></tr>
            <tr v-if="detail.停运原因"><th>停运原因</th><td colspan="3">{{ detail.停运原因 }}</td></tr>
          </tbody>
        </table>
        <h4 class="history-title">巡视 / 缺陷 / 停运历史（历史记录归属不随责任人变更改变）</h4>
        <table class="data-table">
          <thead>
            <tr><th>日期</th><th>类型</th><th>结论</th><th>说明</th><th>归属班组</th><th>提交人</th></tr>
          </thead>
          <tbody>
            <tr v-for="(record, idx) in detail.巡视历史" :key="idx"
                :class="{ 'history-old-team': record.班组 !== detail.所属班组 }">
              <td>{{ record.日期 }}</td>
              <td>{{ record.类型 }}</td>
              <td>{{ record.巡视结论 }}</td>
              <td>{{ record.说明 }}</td>
              <td>{{ record.班组 }}<span v-if="record.班组 !== detail.所属班组" class="tag tag-other">原班组</span></td>
              <td>{{ record.提交人 }}</td>
            </tr>
            <tr v-if="!detail.巡视历史?.length">
              <td colspan="6" class="empty-state">暂无巡视历史</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>
type HistoryRecord = {
  日期: string
  类型: string
  巡视结论: string
  说明: string
  班组: string
  提交人: string
}
type DetailRow = Row & { 巡视历史?: HistoryRecord[]; 停运原因?: string | null }

const ENDPOINT = '/api/collector'
const columns = ['线路编号', '电压等级', '所属场站', '起止杆塔', '线路长度', '所属班组', '责任人', '上次巡视日', '缺陷数量', '线路状态']
const statuses = ['待巡视', '运行正常', '存在缺陷', '已停运']

const session = useSessionStore()
const team = ref(session.collectorTeam)
const operator = ref(session.collectorOperator)
const teams = ref<Record<string, string[]>>({})
const teamNames = computed(() => Object.keys(teams.value))

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([
  { label: '在运线路', value: 0 },
  { label: '存在缺陷线路', value: 0 },
  { label: '待巡视线段', value: 0 },
])
const feedback = ref('')
const feedbackOk = ref(false)
const keyword = ref('')
const statusFilter = ref('')

const dialog = ref<{ action: string; row: Row } | null>(null)
const form = reactive<Record<string, string>>({})
const submitting = ref(false)
const detail = ref<DetailRow | null>(null)

function authHeaders(): Record<string, string> {
  return {
    'X-Operator-Team': team.value,
    'X-Operator-Name': operator.value,
  }
}

function persistIdentity() {
  session.setCollectorIdentity(team.value, operator.value)
}

function onTeamChange() {
  const members = teams.value[team.value] ?? []
  operator.value = members[0] ?? ''
  persistIdentity()
  void reload()
}

function onOperatorChange() {
  persistIdentity()
  void reload()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function showFeedback(message: string, ok: boolean) {
  feedback.value = message
  feedbackOk.value = ok
}

async function loadContext() {
  const response = await request(`${ENDPOINT}/context`, { headers: authHeaders() })
  if (!response.ok) {
    throw new Error('班组名册读取失败')
  }
  const payload = await response.json()
  teams.value = payload.teams ?? {}
  if (!teams.value[team.value]) {
    team.value = Object.keys(teams.value)[0] ?? ''
  }
  if (!(teams.value[team.value] ?? []).includes(operator.value)) {
    operator.value = teams.value[team.value]?.[0] ?? ''
  }
  persistIdentity()
  stats.value = [
    { label: '在运线路', value: payload.summary?.['在运线路'] ?? 0 },
    { label: '存在缺陷线路', value: payload.summary?.['存在缺陷线路'] ?? 0 },
    { label: '待巡视线段', value: payload.summary?.['待巡视线段'] ?? 0 },
  ]
}

async function reload() {
  feedback.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`, { headers: authHeaders() })
    if (!response.ok) {
      throw new Error('集电线路列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 提交后重新进入列表：统计随动作结果一起刷新，台账与概览保持同一口径。
    const summaryResponse = await request(`${ENDPOINT}/summary`, { headers: authHeaders() })
    if (summaryResponse.ok) {
      const summary = await summaryResponse.json()
      stats.value = [
        { label: '在运线路', value: summary['在运线路'] ?? 0 },
        { label: '存在缺陷线路', value: summary['存在缺陷线路'] ?? 0 },
        { label: '待巡视线段', value: summary['待巡视线段'] ?? 0 },
      ]
    }
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : '集电线路列表读取失败', false)
  }
}

function openAction(action: string, row: Row) {
  feedback.value = ''
  dialog.value = { action, row }
  Object.keys(form).forEach((key) => delete form[key])
  if (action === '变更责任人') {
    form.新班组 = String(row.所属班组 ?? team.value)
    form.新责任人 = String(row.责任人 ?? teams.value[form.新班组]?.[0] ?? '')
  }
}

function closeDialog() {
  dialog.value = null
}

async function submitAction() {
  if (!dialog.value) return
  const { action, row } = dialog.value
  const values: Record<string, string> = { action, ...form }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      // 越权与校验失败：后端信息里带线路编号，直接指出是哪一项被拦住。
      throw new Error(payload?.detail ?? payload?.message ?? '操作未生效，请稍后重试')
    }
    showFeedback(payload.message, true)
    closeDialog()
    await reload()
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : '集电线路操作失败', false)
  } finally {
    submitting.value = false
  }
}

async function openDetail(row: Row) {
  feedback.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`, { headers: authHeaders() })
    if (!response.ok) {
      throw new Error('线路明细读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : '线路明细读取失败', false)
  }
}

onMounted(async () => {
  try {
    await loadContext()
    await reload()
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : '页面初始化失败', false)
  }
})
</script>

<style scoped>
.identity-bar {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.identity-title { font-size: 13px; font-weight: 600; }
.identity-item { font-size: 12px; color: var(--muted); }
.identity-item select { margin-top: 2px; padding: 4px 6px; }
.identity-hint { font-size: 12px; color: var(--muted); }
.collector-table .row-readonly { background: #fafbfc; }
.collector-table .row-stopped { background: #f5f5f4; }
.tag {
  display: inline-block;
  font-size: 11px;
  line-height: 16px;
  padding: 0 6px;
  border-radius: 8px;
  margin-left: 4px;
}
.tag-self { background: #e8f1ff; color: #1f6feb; }
.tag-other { background: #f1f5f9; color: #64748b; }
.tag-stop { background: #fef3c7; color: #92400e; }
.link-danger { color: #b42318; }
.link-detail { color: var(--muted); }
.readonly-text { font-size: 12px; color: var(--muted); }
.success-text { color: #15803d; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  width: 460px;
  max-width: calc(100vw - 32px);
  padding: 18px 20px;
}
.modal-wide { width: 820px; max-height: 86vh; overflow: auto; }
.modal h3 { margin: 0 0 4px; font-size: 16px; }
.modal-sub { margin: 0 0 12px; font-size: 12px; color: var(--muted); }
.modal-tip { font-size: 12px; color: #92400e; background: #fefce8; border-radius: 6px; padding: 6px 8px; }
.form-item { display: block; margin-bottom: 10px; font-size: 13px; }
.form-item span { display: block; margin-bottom: 4px; color: #334155; }
.form-item em { color: #b42318; font-style: normal; }
.form-item input,
.form-item select,
.form-item textarea {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font: inherit;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.detail-table th { width: 120px; background: #f8fafc; }
.history-title { font-size: 14px; margin: 14px 0 6px; }
.history-old-team { background: #fafaf9; }
</style>
