<script setup lang="ts">
import { computed, ref } from 'vue'
import { formatMinorUnits, sumMinorUnits } from './money'

// T01 placeholder view. The real workbench (consumer intake, staff review,
// timeline, SSE resume) is T28; this exists so the toolchain is exercised by
// buildable, testable code rather than an empty shell.
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

const totalMinor = computed(() => sumMinorUnits(rows.value.map((row) => row.amountMinor)))
</script>

<template>
  <main>
    <h1>ResolveFlow 工单工作台</h1>
    <table>
      <thead>
        <tr><th>工单</th><th>动作</th><th>金额</th><th>状态</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.caseId">
          <td>{{ row.caseId }}</td>
          <td>{{ row.action }}</td>
          <td>{{ formatMinorUnits(row.amountMinor) }}</td>
          <td>{{ row.state }}</td>
        </tr>
      </tbody>
    </table>
    <p>合计：{{ formatMinorUnits(totalMinor) }}</p>
  </main>
</template>
