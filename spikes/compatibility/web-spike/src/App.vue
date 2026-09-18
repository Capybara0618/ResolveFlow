<script setup lang="ts">
import { computed, ref } from 'vue'

// Minimal typed component: the point is that <script setup> + strict TS + SFC
// compilation all work on the fixed toolchain, not that this UI does anything.
interface CaseRow {
  caseId: string
  action: 'REFUND' | 'RESHIP'
  amountMinor: number
  state: string
}

const rows = ref<CaseRow[]>([
  { caseId: 'c-9001', action: 'REFUND', amountMinor: 20000, state: 'PENDING_REVIEW' },
  { caseId: 'c-9002', action: 'RESHIP', amountMinor: 0, state: 'EXECUTING' },
])

const totalMinor = computed(() =>
  rows.value.reduce((sum, row) => sum + row.amountMinor, 0),
)

function formatMinor(amountMinor: number): string {
  // Money is integer minor units end to end; formatting happens only for display.
  return (amountMinor / 100).toFixed(2)
}
</script>

<template>
  <main>
    <h1>ResolveFlow · T00 前端构建验证</h1>
    <table>
      <thead>
        <tr><th>工单</th><th>动作</th><th>金额</th><th>状态</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.caseId">
          <td>{{ row.caseId }}</td>
          <td>{{ row.action }}</td>
          <td>{{ formatMinor(row.amountMinor) }}</td>
          <td>{{ row.state }}</td>
        </tr>
      </tbody>
    </table>
    <p>合计：{{ formatMinor(totalMinor) }}</p>
  </main>
</template>