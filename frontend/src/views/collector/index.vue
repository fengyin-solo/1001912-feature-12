<template>
  <section class="page" data-module="collector">
    <header class="page-head">
      <div>
        <h2>集电线路管理</h2>
        <p class="page-desc">
          按线路所属班组收口：本班组只能提交本班组线路的巡视结果与缺陷登记，其他班组只能查看；
          停运申请由线路责任人提交并写明原因。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出集电线路清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>线路编号</span>
        <input v-model="filters.keyword" placeholder="按线路编号检索" />
      </label>
      <label class="filter-item">
        <span>所属班组</span>
        <select v-model="filters.team">
          <option value="">全部班组</option>
          <option v-for="team in store.teams" :key="team.name" :value="team.name">{{ team.name }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>线路状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      <label class="filter-item scope-check">
        <input v-model="onlyMine" type="checkbox" @change="reload" />
        只看本班组（{{ store.currentTeam ?? '非班组账号' }}）
      </label>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th style="min-width: 220px">操作（按所属班组收口）</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-blocked': blockedRowId === row.id }">
          <td v-for="column in columns" :key="column" :class="cellClass(column, row)">
            <template v-if="column === '线路状态'">
              <span class="status-tag" :data-status="row[column]">{{ row[column] }}</span>
            </template>
            <template v-else-if="column === '停运原因'">
              <span :title="String(row[column] ?? '')">{{ row[column] || '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">台账/记录</button>
            <template v-if="isOwn(row)">
              <button
                class="link"
                type="button"
                :disabled="isStopped(row)"
                :title="isStopped(row) ? '已停运线路不能提交巡视，仅可登记/消除缺陷' : ''"
                @click="openDialog('patrol', row)"
              >
                提交巡视
              </button>
              <button class="link" type="button" @click="openDialog('defect', row)">登记缺陷</button>
              <button
                v-if="!isStopped(row)"
                class="link danger"
                type="button"
                :class="{ 'link-disabled': !isOwner(row) }"
                :title="isOwner(row) ? '' : `停运申请仅限责任人「${row['责任人']}」提交`"
                @click="isOwner(row) ? openDialog('stop', row) : flagBlocked(row, `停运申请必须由责任人「${row['责任人']}」提交，当前操作人不是该线路责任人`)"
              >
                申请停运
              </button>
              <span v-else class="readonly-hint">已停运</span>
            </template>
            <template v-else>
              <span class="readonly-hint" :title="`该线路归属${row['所属班组']}，当前账号只能查看`">
                只读 · 归属{{ row['所属班组'] }}
              </span>
            </template>
            <button
              v-if="store.isAdmin()"
              class="link"
              type="button"
              @click="openDialog('owner', row)"
            >
              变更责任人
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">当前条件下暂无集电线路数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条集电线路记录 · 待巡视数口径与运营概览一致</span>
      <span v-if="errorMessage" class="error-text">⛔ {{ errorMessage }}</span>
      <span v-else-if="successMessage" class="success-text">✅ {{ successMessage }}</span>
    </footer>

    <!-- 动作弹窗：巡视 / 缺陷 / 停运 / 变更责任人 -->
    <div v-if="dialog.mode" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialogTitle }} · {{ dialog.line?.['线路编号'] }}</h3>
        <p class="modal-sub">
          {{ dialog.line?.['起止杆塔'] }}｜归属{{ dialog.line?.['所属班组'] }}｜责任人：{{ dialog.line?.['责任人'] }}
        </p>

        <div v-if="dialog.mode === 'patrol'" class="form-grid">
          <label>
            <span>巡视日期</span>
            <input v-model="form.巡视日期" type="date" />
          </label>
          <label>
            <span>巡视结论 *</span>
            <select v-model="form.巡视结论">
              <option value="" disabled>请选择巡视结论</option>
              <option value="运行正常">运行正常</option>
              <option value="存在缺陷">存在缺陷</option>
            </select>
          </label>
          <label class="full">
            <span>问题/缺陷描述（结论为「存在缺陷」时必填）</span>
            <textarea
              v-model="form.问题描述"
              rows="3"
              :disabled="form.巡视结论 === '运行正常'"
              placeholder="发现缺陷时必须写明位置与现象；运行正常时无需填写"
            ></textarea>
          </label>
          <label v-if="form.巡视结论 === '存在缺陷'">
            <span>缺陷等级 *</span>
            <select v-model="form.缺陷等级">
              <option value="一般">一般</option>
              <option value="严重">严重</option>
              <option value="紧急">紧急</option>
            </select>
          </label>
        </div>

        <div v-else-if="dialog.mode === 'defect'" class="form-grid">
          <label>
            <span>登记日期</span>
            <input v-model="form.登记日期" type="date" />
          </label>
          <label>
            <span>缺陷等级 *</span>
            <select v-model="form.缺陷等级">
              <option value="一般">一般</option>
              <option value="严重">严重</option>
              <option value="紧急">紧急</option>
            </select>
          </label>
          <label class="full">
            <span>缺陷内容 *</span>
            <textarea v-model="form.缺陷内容" rows="3" placeholder="写明缺陷位置、现象与影响"></textarea>
          </label>
        </div>

        <div v-else-if="dialog.mode === 'stop'" class="form-grid">
          <label class="full">
            <span>停运原因 *（仅线路责任人可提交）</span>
            <textarea v-model="form.停运原因" rows="3" placeholder="例如：N58 杆塔基础沉降，电缆头放电，需停电消缺"></textarea>
          </label>
        </div>

        <div v-else-if="dialog.mode === 'owner'" class="form-grid">
          <label>
            <span>调整后所属班组 *</span>
            <select v-model="form.所属班组">
              <option v-for="team in store.teams" :key="team.name" :value="team.name">{{ team.name }}</option>
            </select>
          </label>
          <label>
            <span>调整后责任人 *（须为该班组成员）</span>
            <select v-model="form.责任人">
              <option v-for="member in ownerCandidates" :key="member" :value="member">{{ member }}</option>
            </select>
          </label>
          <p class="modal-note full">历史巡视记录保留提交时的班组与人名快照，责任人变更不改动历史归属。</p>
        </div>

        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitDialog">
            {{ submitting ? '提交中…' : '提交' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 台账/记录详情：核对责任归属、巡视结论与缺陷 -->
    <div v-if="detail.line" class="modal-mask" @click.self="closeDetail">
      <div class="modal modal-wide">
        <h3>台账与历史记录 · {{ detail.line['线路编号'] }}</h3>
        <p class="modal-sub">
          {{ detail.line['起止杆塔'] }}｜{{ detail.line['线路长度'] }}｜{{ detail.line['所属场站'] }}｜
          归属{{ detail.line['所属班组'] }}｜责任人：{{ detail.line['责任人'] }}｜
          当前状态：<span class="status-tag" :data-status="detail.line['线路状态']">{{ detail.line['线路状态'] }}</span>
          <template v-if="detail.line['停运原因']">｜停运原因：{{ detail.line['停运原因'] }}</template>
        </p>

        <h4 class="detail-h">巡视记录（历史归属以记录内班组为准）</h4>
        <table class="data-table sub-table">
          <thead>
            <tr><th>巡视单号</th><th>巡视日期</th><th>巡视结论</th><th>巡视人</th><th>巡视班组</th><th>问题描述</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in detail.patrols" :key="String(p.id)">
              <td>{{ p['巡视单号'] }}</td>
              <td>{{ p['巡视日期'] }}</td>
              <td><span class="status-tag" :data-status="p['巡视结论']">{{ p['巡视结论'] }}</span></td>
              <td>{{ p['巡视人'] }}</td>
              <td>{{ p['巡视班组'] }}</td>
              <td>{{ p['问题描述'] || '—' }}</td>
            </tr>
            <tr v-if="!detail.patrols.length"><td colspan="6" class="empty-state">暂无巡视记录</td></tr>
          </tbody>
        </table>

        <h4 class="detail-h">缺陷登记（台账「缺陷数量」按未消除缺陷统计）</h4>
        <table class="data-table sub-table">
          <thead>
            <tr><th>缺陷编号</th><th>缺陷内容</th><th>等级</th><th>登记日期</th><th>登记人/班组</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in detail.defects" :key="String(d.id)">
              <td>{{ d['缺陷编号'] }}</td>
              <td>{{ d['缺陷内容'] }}</td>
              <td>{{ d['缺陷等级'] }}</td>
              <td>{{ d['登记日期'] }}</td>
              <td>{{ d['登记人'] }} / {{ d['登记班组'] }}</td>
              <td>{{ d.open ? '未消除' : `已消除（${d['消除人']} ${d['消除日期']}）` }}</td>
              <td>
                <button
                  v-if="d.open && isOwn(detail.line)"
                  class="link"
                  type="button"
                  @click="resolveDefect(Number(d.id))"
                >
                  消除缺陷
                </button>
                <span v-else-if="d.open" class="readonly-hint">只读</span>
                <span v-else>—</span>
              </td>
            </tr>
            <tr v-if="!detail.defects.length"><td colspan="7" class="empty-state">暂无缺陷记录</td></tr>
          </tbody>
        </table>

        <div class="modal-actions">
          <button class="btn primary" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>
type PatrolRow = Record<string, string | number | boolean | null>
type DialogMode = 'patrol' | 'defect' | 'stop' | 'owner'

const ENDPOINT = '/api/collector'
const columns = [
  '线路编号', '电压等级', '起止杆塔', '线路长度', '所属场站', '所属班组',
  '责任人', '上次巡视日', '缺陷数量', '线路状态', '停运原因',
]
const statuses = ['待巡视', '运行正常', '存在缺陷', '已停运']

const store = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const statCards = ref([
  { label: '在运线路', value: 0 },
  { label: '存在缺陷线路', value: 0 },
  { label: '待巡视线段', value: 0 },
  { label: '已停运线路', value: 0 },
])
const errorMessage = ref('')
const successMessage = ref('')
const blockedRowId = ref<number | null>(null)
const filters = ref({ keyword: '', team: '', status: '' })
const onlyMine = ref(false)
const submitting = ref(false)

const dialog = reactive<{ mode: DialogMode | null; line: Row | null }>({ mode: null, line: null })
const form = reactive<Record<string, string>>({})

const detail = reactive<{
  line: Row | null
  patrols: PatrolRow[]
  defects: PatrolRow[]
}>({ line: null, patrols: [], defects: [] })

const dialogTitle = computed(() => ({
  patrol: '提交巡视结果（本班组）',
  defect: '登记缺陷（本班组）',
  stop: '申请停运（责任人）',
  owner: '变更责任人（管理员）',
}[dialog.mode ?? 'patrol']))

const ownerCandidates = computed(() => {
  const team = store.teams.find((item) => item.name === form.所属班组)
  return team ? team.members : []
})

function today() {
  return new Date().toISOString().slice(0, 10)
}

function isOwn(row: Row) {
  return store.currentTeam !== null && store.currentTeam === row['所属班组']
}

function isOwner(row: Row) {
  return store.operator === row['责任人']
}

function isStopped(row: Row) {
  return row['线路状态'] === '已停运'
}

function cellClass(column: string, row: Row) {
  if (column === '所属班组') {
    return isOwn(row) ? 'cell-own' : 'cell-other'
  }
  return ''
}

function resetFilters() {
  filters.value = { keyword: '', team: '', status: '' }
  onlyMine.value = false
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, 'blank')
}

function flagBlocked(row: Row, message: string) {
  blockedRowId.value = Number(row.id)
  errorMessage.value = `【${row['线路编号']}（${row['起止杆塔']}）】${message}`
  successMessage.value = ''
}

function openDialog(mode: DialogMode, row: Row) {
  dialog.mode = mode
  dialog.line = row
  blockedRowId.value = null
  errorMessage.value = ''
  for (const key of Object.keys(form)) {
    delete form[key]
  }
  if (mode === 'patrol') {
    form.巡视日期 = today()
    form.巡视结论 = ''
    form.问题描述 = ''
    form.缺陷等级 = '一般'
  } else if (mode === 'defect') {
    form.登记日期 = today()
    form.缺陷等级 = '一般'
    form.缺陷内容 = ''
  } else if (mode === 'stop') {
    form.停运原因 = ''
  } else {
    form.所属班组 = String(row['所属班组'] ?? '')
    form.责任人 = String(row['责任人'] ?? '')
  }
}

function closeDialog() {
  dialog.mode = null
  dialog.line = null
}

async function submitDialog() {
  if (!dialog.line || !dialog.mode) {
    return
  }
  const id = dialog.line.id
  const pathMap: Record<DialogMode, string> = {
    patrol: `${ENDPOINT}/${id}/patrol`,
    defect: `${ENDPOINT}/${id}/defects`,
    stop: `${ENDPOINT}/${id}/stop`,
    owner: `${ENDPOINT}/${id}/owner`,
  }
  submitting.value = true
  try {
    const payload: Record<string, string> = { operator: store.operator, ...form }
    const data = await postAction(pathMap[dialog.mode], payload)
    closeDialog()
    await reload()
    successMessage.value = data.message
    errorMessage.value = ''
    blockedRowId.value = null
    if (detail.line && detail.line.id === id) {
      void openDetailById(Number(id))
    }
  } catch (error) {
    blockedRowId.value = Number(id)
    errorMessage.value = error instanceof Error ? error.message : '操作未生效'
    successMessage.value = ''
  } finally {
    submitting.value = false
  }
}

async function postAction(path: string, values: Record<string, string>) {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  let data: { ok?: boolean; message?: string } = {}
  try {
    data = await response.json()
  } catch {
    data = {}
  }
  // 后端对业务/权限拦截统一返回 ok:false，并在 message 里指出是哪一条线路的哪一项
  if (!response.ok || data.ok === false) {
    throw new Error(data.message || '操作未被服务端接受')
  }
  return data as { ok: boolean; message: string }
}

async function resolveDefect(defectId: number) {
  if (!detail.line) {
    return
  }
  const lineId = detail.line.id
  try {
    const data = await postAction(`${ENDPOINT}/defects/${defectId}/resolve`, {
      operator: store.operator,
      消除日期: today(),
    })
    successMessage.value = data.message
    errorMessage.value = ''
    await Promise.all([reload(), openDetailById(Number(lineId))])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺陷消除失败'
    successMessage.value = ''
  }
}

async function openDetailById(id: number) {
  const response = await request(`${ENDPOINT}/${id}/detail`)
  if (!response.ok) {
    throw new Error('线路详情读取失败')
  }
  const data = await response.json()
  detail.line = data.line
  detail.patrols = data.patrols ?? []
  detail.defects = data.defects ?? []
}

async function openDetail(row: Row) {
  try {
    await openDetailById(Number(row.id))
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '线路详情读取失败'
  }
}

function closeDetail() {
  detail.line = null
  detail.patrols = []
  detail.defects = []
}

async function reload() {
  const params = new URLSearchParams()
  if (filters.value.keyword.trim()) {
    params.set('keyword', filters.value.keyword.trim())
  }
  if (filters.value.status) {
    params.set('status', filters.value.status)
  }
  const team = onlyMine.value && store.currentTeam ? store.currentTeam : filters.value.team
  if (team) {
    params.set('team', team)
  }
  params.set('size', '200')
  try {
    const [listResp, statsResp] = await Promise.all([
      request(`${ENDPOINT}?${params.toString()}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResp.ok) {
      throw new Error('集电线路列表读取失败')
    }
    const payload = await listResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (statsResp.ok) {
      const stats = await statsResp.json()
      statCards.value = [
        { label: '在运线路', value: stats['在运线路'] ?? 0 },
        { label: '存在缺陷线路', value: stats['存在缺陷线路'] ?? 0 },
        { label: '待巡视线段', value: stats['待巡视线段'] ?? 0 },
        { label: '已停运线路', value: stats['已停运线路'] ?? 0 },
      ]
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集电线路列表读取失败'
  }
}

onMounted(async () => {
  try {
    await store.ensureTeams()
  } finally {
    await reload()
  }
})
</script>
