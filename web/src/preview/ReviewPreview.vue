<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '../ui/ReviewIcon.vue'
import headphones from './assets/headphones.svg'
import './review-preview.css'
import ReviewDialog from '../ui/ReviewDialog.vue'

type Decision = 'approve' | 'request' | 'reject'
type Detail = 'photo' | 'record' | 'device' | 'policy' | 'order' | 'authorization'
const cases = ref([
  { id: '0012', day: '28', time: '14:22', status: '待审核', name: '张**', product: 'XX 无线降噪耳机 Pro', variant: '深空灰', amount: 329,
    title: '商品出现质量问题，申请全额退款', member: '普通会员', phone: '138****6621', email: 'zhang**@qq.com',
    description: '收到耳机后，右耳有明显的电流杂音，尝试重置和更换设备仍然存在问题。这个是新买的产品，无法正常使用，申请全额退款。',
    recommendation: '建议批准退款', reason: '客户反馈右耳持续出现电流杂音，重置及更换设备后仍未改善。结合人工核验记录，符合《售后政策》中“签收后 7 天内质量问题支持全额退款”的条件，建议批准全额退款。', checked: true },
  { id: '0011', day: '28', time: '11:03', status: '待补充', name: '李**', product: 'XX 便携蓝牙音箱 Mini', variant: '雾霭蓝', amount: 199,
    title: '未收到商品，申请全额退款', member: '普通会员', phone: '139****2180', email: 'li**@qq.com',
    description: '物流显示运输中，但已经几天没有更新。我还没有收到商品，希望核查包裹状态，并协助处理退款。',
    recommendation: '建议补充物流凭证', reason: '目前只有客户未收到商品的陈述，尚无承运商确认丢失的记录。建议补充物流查询记录，核实包裹状态后再决定是否退款。', checked: false },
  { id: '0098', day: '27', time: '16:40', status: '待审核', name: '王**', product: 'XX 无线降噪耳机 Max', variant: '月光银', amount: 459,
    title: '收到商品与描述不符，申请退款', member: '普通会员', phone: '137****5306', email: 'wang**@qq.com',
    description: '收到的耳机颜色和下单时选择的颜色不一致，包装上的型号也有差异，已提交开箱图片，希望人工核对处理。',
    recommendation: '建议人工复核', reason: '客户陈述涉及型号与颜色不一致，需进一步核对订单规格、包装标签及实物材料。现有材料不足以直接批准退款，建议先人工复核。', checked: false },
])
const selectedId = ref('0012')
const selected = computed(() => cases.value.find(item => item.id === selectedId.value)!)
const money = (value: number) => value.toFixed(2)
const toast = ref('')
const query = ref('')
const searchOpen = ref(false)
const visibleCases = computed(() => cases.value.filter(item => `${item.id}${item.title}${item.name}`.includes(query.value.trim())))
const modal = ref<Detail | Decision | null>(null)
const reason = ref('')
const decisions: Record<Decision, { title: string; label: string; status: string }> = {
  approve: { title: '批准退款授权', label: '确认批准', status: '已批准' },
  request: { title: '要求补充信息', label: '发送补证请求', status: '待补充' },
  reject: { title: '拒绝退款申请', label: '确认拒绝', status: '已拒绝' },
}
const activeDecision = computed(() => modal.value && modal.value in decisions ? decisions[modal.value as Decision] : null)
const canApprove = computed(() => selected.value.checked && selected.value.status === '待审核')
const canReview = computed(() => !['已批准', '已拒绝'].includes(selected.value.status))
const modalTitle = computed(() => activeDecision.value?.title ?? ({ photo: '图片凭证 · IMG_3281.jpg', record: '问题检测记录', device: '设备信息', policy: '售后政策 · 质量问题退换', order: '订单详情', authorization: '退款授权规则' } as Record<string, string>)[modal.value ?? ''])
function openModal(value: Detail | Decision) { modal.value = value; reason.value = '' }
function closeModal() { modal.value = null }
function submitDecision() {
  if (!activeDecision.value || !reason.value.trim()) return
  selected.value.status = activeDecision.value.status
  toast.value = '演示操作已完成，未提交真实工单。刷新页面可重置。'
  closeModal()
}
function selectCase(id: string) { selectedId.value = id; toast.value = '' }
</script>

<template>
  <div class="review-preview">
    <header class="rp-topbar">
      <a class="rp-brand" href="?preview=review" aria-label="ResolveFlow 设计预览"><span class="rp-brand-mark"><i /><i /><i /><i /></span>ResolveFlow</a>
      <span class="rp-preview-badge">设计预览 · 合成数据</span>
      <div class="rp-user"><span class="rp-notification"><Icon name="bell" :size="21" /><i /></span><span class="rp-avatar">林</span><span><strong>林晓云</strong><small>售后审核员</small></span><Icon name="down" :size="15" /></div>
    </header>
    <div class="rp-workspace">
      <nav class="rp-sidebar" aria-label="预览导航">
        <div><button class="rp-nav-item" :class="{ active: !searchOpen }" @click="searchOpen = false; query = ''"><Icon name="queue" />审核队列<span class="rp-nav-count">{{ cases.length }}</span></button>
          <button class="rp-nav-item" :class="{ active: searchOpen }" @click="searchOpen = !searchOpen"><Icon name="search" />工单查询</button></div>
        <div class="rp-sidebar-note"><span>让售后更简单</span><span>让每一次服务都有结果</span><small>© 2026 ResolveFlow</small></div>
      </nav>

      <aside class="rp-queue" aria-label="审核队列">
        <div class="rp-queue-heading"><h2>审核队列 <span>（{{ visibleCases.length }}）</span></h2><span class="rp-sort">创建时间从新到旧<Icon name="down" :size="12" /></span></div>
        <label v-if="searchOpen" class="rp-search"><Icon name="search" :size="16" /><input v-model="query" placeholder="搜索编号、诉求或客户" aria-label="搜索工单" /></label>
        <div class="rp-queue-list"><button v-for="item in visibleCases" :key="item.id" class="rp-queue-card" :class="{ selected: selectedId === item.id }" :data-test="`case-${item.id}`" :aria-pressed="selectedId === item.id" @click="selectCase(item.id)">
          <div class="rp-queue-id"><span>#RF2609{{ item.day }}-{{ item.id }}</span><span class="rp-tag" :class="item.status === '待补充' ? 'amber' : item.status === '已批准' ? 'green' : 'rose'">{{ item.status }}</span></div>
          <strong>{{ item.title }}</strong><div class="rp-queue-meta"><span>¥ {{ money(item.amount) }}</span><i />{{ item.name }}<i />09-{{ item.day }} {{ item.time }}</div>
        </button><p v-if="!visibleCases.length" class="rp-no-results">没有找到匹配工单</p></div>
      </aside>

      <main class="rp-document" aria-label="退款工单详情">
        <div class="rp-case-content">
          <header class="rp-case-heading"><div><h1>退款工单<span class="rp-tag" :class="selected.status === '待补充' ? 'amber' : selected.status === '已批准' ? 'green' : 'rose'" data-test="case-status">{{ selected.status }}</span></h1><p><span>提交时间：2026-09-{{ selected.day }} {{ selected.time }}</span><span data-test="case-number">工单编号：RF2609{{ selected.day }}-{{ selected.id }}</span></p></div></header>

          <section class="rp-order-card"><div class="rp-section-heading"><h2>订单信息</h2><button class="rp-text-button rp-order-id" @click="openModal('order')">订单号：OD2026091504821<Icon name="chevron" :size="14" /></button></div>
            <div class="rp-order-row"><div class="rp-product-thumb"><img v-if="selected.id !== '0011'" :src="headphones" alt="合成商品：银灰色无线耳机" /><Icon v-else name="box" :size="34" /></div><div class="rp-product-name" data-test="order-product"><strong>{{ selected.product }}</strong><span>{{ selected.variant }}<i />数量 ×1</span></div>
              <div class="rp-price-block"><span>订单金额</span><strong>¥ {{ money(selected.amount) }}</strong></div><div class="rp-price-block refund"><span>申请退款金额</span><strong>¥ {{ money(selected.amount) }}<small>（全额退款）</small></strong></div><button class="rp-text-button rp-order-link" @click="openModal('order')">查看订单<Icon name="chevron" :size="13" /></button></div>
          </section>

          <section class="rp-issue-section"><div class="rp-section-heading"><h2>客户问题描述</h2><time>2026-09-{{ selected.day }} {{ selected.time }}</time></div><p class="rp-issue">{{ selected.description }}</p></section>

          <section class="rp-evidence-section"><div class="rp-section-heading"><h2>客户提交的凭证 <span>（{{ selected.checked ? 3 : 1 }}）</span></h2><button class="rp-text-button" @click="openModal(selected.checked ? 'photo' : 'record')">查看材料<Icon name="chevron" :size="13" /></button></div>
            <div v-if="selected.checked" class="rp-evidence-grid">
              <button class="rp-evidence-card" data-test="evidence-photo" @click="openModal('photo')"><span class="rp-evidence-thumb photo"><img :src="headphones" alt="合成耳机图片凭证" /><span class="rp-thumb-icon"><Icon name="image" :size="13" /></span></span><span class="rp-evidence-info"><strong>图片凭证</strong><span>IMG_3281.jpg</span><small>2.4 MB · 14:20</small><span class="rp-verified"><Icon name="check" :size="13" />已人工核验</span></span></button>
              <button class="rp-evidence-card" @click="openModal('record')"><span class="rp-evidence-thumb recording"><Icon name="file" :size="27" /><span class="rp-wave"><i v-for="(height, index) in [12,24,17,35,28,16,30,20,12]" :key="index" :style="{ height: `${height}px` }" /></span><small>检测记录</small></span><span class="rp-evidence-info"><strong>问题检测记录</strong><span>audio_test.txt</span><small>4.8 KB · 14:21</small><span class="rp-verified"><Icon name="check" :size="13" />已人工核验</span></span></button>
              <button class="rp-evidence-card" @click="openModal('device')"><span class="rp-evidence-thumb device"><span class="rp-mini-window"><b>设备信息</b><span>设备名称</span><i /><span>固件版本</span><i /><span>连接状态</span><i /></span></span><span class="rp-evidence-info"><strong>设备信息</strong><span>system_info.txt</span><small>1.1 KB · 14:21</small><span class="rp-verified"><Icon name="check" :size="13" />已人工核验</span></span></button>
            </div>
            <button v-else class="rp-statement-card" @click="openModal('record')"><span class="rp-material-icon"><Icon name="file" :size="24" /></span><span><strong>客户情况说明</strong><small>{{ selected.description }}</small></span><span class="rp-tag amber">待核验</span><Icon name="chevron" :size="16" /></button>
          </section>

          <section class="rp-investigation"><div class="rp-advice"><h2>Agent 调查建议<span class="rp-sample-label">示例内容</span></h2><div class="rp-recommendation"><span class="rp-sparkle"><Icon name="sparkle" :size="19" /></span><strong data-test="recommendation">{{ selected.recommendation }}</strong><span v-if="selected.checked" class="rp-ready">依据已齐备</span></div><p class="rp-advice-reason">{{ selected.reason }}</p><div class="rp-citations"><h3>引用的政策与证据</h3><button @click="openModal('policy')"><Icon name="file" :size="16" />《售后政策》· 3.1 质量问题退换<Icon name="chevron" :size="12" /></button><button @click="openModal('record')"><Icon name="shield" :size="16" />{{ selected.checked ? '客户材料的人工核验记录' : '客户提交的情况说明（待核验）' }}<Icon name="chevron" :size="12" /></button><button v-if="selected.checked" @click="openModal('device')"><Icon name="file" :size="16" />客户提供的设备信息<Icon name="chevron" :size="12" /></button></div></div>
            <aside class="rp-timeline"><h3>调查时间线</h3><ol><li><time>2026-09-{{ selected.day }} {{ selected.time }}</time><strong>工单创建</strong></li><li><time>2026-09-{{ selected.day }} 14:24</time><strong>订单与退款记录核对</strong><span>未发现重复退款</span></li><li><time>2026-09-{{ selected.day }} 14:26</time><strong>{{ selected.checked ? '客户材料人工核验完成' : '等待补充材料' }}</strong><span>{{ selected.checked ? '3 项材料已核对' : '现有证据尚不充分' }}</span></li><li :class="{ current: true }"><time>2026-09-{{ selected.day }} 14:28</time><strong>生成调查建议</strong></li></ol></aside>
          </section>
        </div>
        <footer class="rp-decision"><div class="rp-decision-heading"><h2>审核决策</h2><span>批准后进入模拟退款执行</span></div><div class="rp-decision-actions"><button class="rp-primary" data-test="approve" :disabled="!canApprove" @click="openModal('approve')"><Icon name="check" :size="19" />批准退款</button><button class="rp-secondary" :disabled="!canReview" @click="openModal('request')"><Icon name="file" :size="17" />要求补充信息</button><button class="rp-danger" :disabled="!canReview" @click="openModal('reject')"><Icon name="close" :size="18" />拒绝</button></div></footer>
      </main>

      <aside class="rp-context" aria-label="客户订单与授权信息">
        <section class="rp-context-card"><h2>客户与订单信息</h2><dl><dt>客户昵称</dt><dd data-test="customer-name">{{ selected.name }}</dd><dt>会员等级</dt><dd>{{ selected.member }}</dd><dt>注册时间</dt><dd>2024-05-12</dd><dt>联系电话</dt><dd>{{ selected.phone }}</dd><dt>邮箱</dt><dd>{{ selected.email }}</dd></dl></section>
        <section class="rp-context-card"><h2>支付信息</h2><dl><dt>支付方式</dt><dd>支付宝</dd><dt>支付时间</dt><dd>2026-09-15 10:36</dd><dt>支付金额</dt><dd>¥ {{ money(selected.amount) }}</dd><dt>交易编号</dt><dd class="rp-transaction">20260915103628241</dd></dl></section>
        <section class="rp-context-card rp-rules"><h2>退款限制校验</h2><ul><li><span class="rp-check-dot"><Icon name="check" :size="12" /></span><span>退款金额不超过实付</span><b>符合</b></li><li><span class="rp-check-dot"><Icon name="check" :size="12" /></span><span>未发生重复退款</span><b>符合</b></li><li><span class="rp-check-dot" :class="{ pending: !selected.checked }"><Icon :name="selected.checked ? 'check' : 'clock'" :size="12" /></span><span>客户材料已人工核验</span><b :class="{ pending: !selected.checked }">{{ selected.checked ? '符合' : '待核验' }}</b></li><li><span class="rp-check-dot"><Icon name="check" :size="12" /></span><span>单订单行全额退款</span><b>符合</b></li></ul></section>
        <section class="rp-context-card rp-authorization"><h2>授权状态</h2><div class="rp-auth-status"><span class="rp-auth-icon"><Icon name="shield" :size="21" /></span><div><strong>{{ selected.status === '已批准' ? '已批准退款授权' : selected.status === '已拒绝' ? '退款申请已拒绝' : selected.checked ? '等待人工审批' : '待补充后重新核验' }}</strong><p>{{ selected.checked ? '材料与金额已核对，等待审核员决定' : '证据补齐前暂不可批准退款' }}</p></div></div><dl><dt>本单申请金额</dt><dd>¥ {{ money(selected.amount) }}</dd></dl><button class="rp-text-button" @click="openModal('authorization')">查看授权规则<Icon name="chevron" :size="13" /></button></section>
        <p class="rp-demo-note"><Icon name="shield" :size="13" />此页面仅用于视觉与交互预览</p>
      </aside>
    </div>
    <div v-if="toast" class="rp-toast" role="status"><Icon name="check" />{{ toast }}<button aria-label="关闭提示" @click="toast = ''"><Icon name="close" :size="16" /></button></div>
    <ReviewDialog v-if="modal" :title="modalTitle" @close="closeModal">
        <template v-if="activeDecision"><p class="rp-modal-copy">工单 RF2609{{ selected.day }}-{{ selected.id }} · {{ selected.name }} · ¥ {{ money(selected.amount) }}</p><label class="rp-reason-label" for="preview-reason">{{ modal === 'request' ? '需要客户补充的内容' : '审核理由' }}<span>必填</span></label><textarea id="preview-reason" v-model="reason" rows="4" maxlength="500" placeholder="请写明审核依据或需要补充的材料…" /><p class="rp-preview-notice">此操作只改变当前预览，不会提交真实工单或执行退款。</p><footer><button class="rp-secondary" @click="closeModal">取消</button><button class="rp-primary" data-test="confirm-decision" :disabled="!reason.trim()" @click="submitDecision">{{ activeDecision.label }}</button></footer></template>
        <template v-else-if="modal === 'photo'"><img class="rp-expanded-photo" :src="headphones" alt="合成耳机展示图片，非真实客户上传材料" /><p class="rp-preview-notice">本地绘制的演示插画，用于验证图片凭证的展示布局。</p></template>
        <template v-else-if="modal === 'policy'"><span class="rp-tag blue">政策示例 · v2026.09</span><h3>3.1 质量问题退换</h3><p class="rp-modal-copy">签收后 7 天内，如商品存在影响正常使用的质量问题，经人工核验后可申请该订单行全额退款。退款金额不得超过订单行实付金额，已成功退款的订单行不可重复退款。</p><p class="rp-preview-notice">用于设计预览的示例条款；接入后展示服务端钉住版本及引用。</p></template>
        <template v-else-if="modal === 'order'"><div class="rp-modal-product"><img :src="headphones" alt="合成商品展示素材" /><div><h3>{{ selected.product }}</h3><p>{{ selected.variant }} · 数量 1</p><strong>¥ {{ money(selected.amount) }}</strong></div></div><dl class="rp-modal-dl"><dt>订单编号</dt><dd>OD2026091504821</dd><dt>订单状态</dt><dd>已支付</dd><dt>客户</dt><dd>{{ selected.name }}</dd></dl><p class="rp-preview-notice">当前为合成订单信息。</p></template>
        <template v-else-if="modal === 'authorization'"><p class="rp-modal-copy">本样板采用人工审批流程。审核员核对材料、政策与金额后批准授权；退款执行结果应单独展示，批准授权不等于退款到账。</p><p class="rp-preview-notice">预览操作仅保存在页面内，不建立真实授权。</p></template>
        <template v-else><span class="rp-tag" :class="selected.checked ? 'green' : 'amber'">{{ selected.checked ? '人工核验 · 示例' : '待核验 · 示例' }}</span><h3>{{ modal === 'device' ? '耳机连接与固件信息' : '客户问题与核验记录' }}</h3><p class="rp-modal-copy">{{ modal === 'device' ? '设备型号：XX Pro；固件版本：2.1.0；已尝试恢复出厂设置，并在两台设备上复测。右声道杂音仍然存在。' : selected.description }}</p><p v-if="selected.checked" class="rp-modal-copy">核验说明：已核对客户陈述与检测记录，问题表现一致。此处为人工核验示例，不代表自动识别媒体真实性。</p></template>
    </ReviewDialog>
  </div>
</template>
