<script setup lang="ts">
defineProps<{ asset: string; name: string }>()
</script>
<template>
  <svg class="product-art" viewBox="0 0 400 300" role="img" :aria-label="`${name}商品插画`">
    <ellipse cx="200" cy="255" rx="100" ry="13" fill="#182a42" opacity=".08" />
    <g v-if="asset === 'headphones'" stroke="#26344a" stroke-linecap="round">
      <path d="M114 173V135a86 86 0 0 1 172 0v38" fill="none" stroke-width="19" />
      <path d="M125 125a75 75 0 0 1 149 0" fill="none" stroke="#8290a3" stroke-width="5" />
      <rect x="95" y="142" width="60" height="100" rx="26" fill="#384457" stroke-width="3" transform="rotate(10 125 192)" />
      <rect x="245" y="142" width="60" height="100" rx="26" fill="#384457" stroke-width="3" transform="rotate(-10 275 192)" />
      <path d="M111 166v49M290 166v49" stroke="#5c697c" stroke-width="5" />
    </g>
    <g v-else-if="asset === 'keyboard'">
      <path d="M66 135h268l24 96H42z" fill="#bbc5d2" />
      <path d="M72 123h256l23 90H49z" fill="#fdfefe" stroke="#abb8c8" stroke-width="3" />
      <g v-for="row in 4" :key="row"><rect v-for="col in 11" :key="col" :x="72 + (col-1)*23 - row*3" :y="123+row*18" width="18" height="13" rx="3" :fill="col===11 ? '#9fbbff' : '#e1e7ef'" /></g>
      <rect x="127" y="204" width="127" height="9" rx="3" fill="#d9e1eb" />
    </g>
    <g v-else-if="asset === 'mouse'">
      <path d="M139 154c0-76 122-76 122 0v39c0 78-122 78-122 0z" fill="#7c899a" stroke="#5e6b7e" stroke-width="3" />
      <path d="M200 99v66m-60 0h120" fill="none" stroke="#515f72" stroke-width="3" />
      <rect x="193" y="120" width="14" height="31" rx="7" fill="#354255" />
      <path d="M153 170v29c0 24 12 33 23 38" fill="none" stroke="#9eabba" stroke-width="5" />
    </g>
    <g v-else-if="asset === 'lamp'">
      <ellipse cx="200" cy="244" rx="74" ry="13" fill="#c9c3b8" /><ellipse cx="200" cy="238" rx="74" ry="13" fill="#e5ded0" />
      <path d="M200 234V120" stroke="#c1b7a6" stroke-width="10" />
      <path d="M148 58h104l37 94H111z" fill="#f0e9db" stroke="#d4cabb" stroke-width="2" />
      <ellipse cx="200" cy="152" rx="89" ry="12" fill="#d8c9ac" /><ellipse cx="200" cy="153" rx="74" ry="7" fill="#fff3ce" />
    </g>
    <g v-else-if="asset === 'cup'">
      <path d="M159 87h82l-7 145c-1 26-67 26-68 0z" fill="#c7d2de" stroke="#92a3b6" stroke-width="3" />
      <path d="M174 108l4 123" stroke="#f0f5fa" stroke-width="8" stroke-linecap="round" />
      <rect x="156" y="71" width="88" height="29" rx="11" fill="#6e7d8f" /><ellipse cx="200" cy="73" rx="38" ry="6" fill="#9daaba" />
    </g>
    <g v-else-if="asset === 'pillow'">
      <path d="M103 78q96 18 194 0-20 83 0 166-96-18-194 0 20-83 0-166z" fill="#d8c9b7" stroke="#bba58d" stroke-width="3" />
      <path d="M116 92q85 17 168 0-18 70 0 137-85-17-168 0 18-70 0-137z" fill="none" stroke="#ede2d4" stroke-width="2" />
      <path d="M139 115l120 93m-3-93-115 96" stroke="#c6b5a0" stroke-width="2" opacity=".35" />
    </g>
    <g v-else><rect x="120" y="80" width="160" height="160" rx="20" fill="#d8e5fb" /><path d="M160 160h80" stroke="#7297d6" stroke-width="8" /></g>
  </svg>
</template>
