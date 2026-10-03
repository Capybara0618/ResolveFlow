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
    <g v-else-if="asset === 'backpack' || asset === 'bag'"><path d="M150 86v-8a50 50 0 0 1 100 0v8" fill="none" stroke="#465d70" stroke-width="11" /><rect x="124" y="79" width="152" height="163" rx="38" fill="#66878d" stroke="#3e6871" stroke-width="3" /><rect x="143" y="159" width="114" height="66" rx="17" fill="#8aaba9" /><path d="M153 112h94M154 173h91" stroke="#dbe6de" stroke-width="4" /><path d="M116 117v96m168-96v96" stroke="#456a73" stroke-width="12" /></g>
    <g v-else-if="asset === 'tent'"><path d="M57 238 189 63l154 175z" fill="#d6c4a2" stroke="#9c886b" stroke-width="3" /><path d="m189 63 34 175H57z" fill="#8aa699" /><path d="m189 107 24 131H117z" fill="#405f58" /><path d="m48 243 307 0" stroke="#667665" stroke-width="5" /><path d="m80 191-23 48m259-47 22 47" stroke="#7d8476" stroke-width="2" /></g>
    <g v-else-if="asset === 'chair'"><path d="m114 79 33 111h121l24-111z" fill="#84958b" stroke="#506759" stroke-width="4" /><path d="m146 190-24 55m146-55 24 55m-155-70 132 67m-9-67-132 67" stroke="#52616a" stroke-width="7" /><path d="m111 127 29 70m157-70-31 70" stroke="#53676b" stroke-width="9" /></g>
    <g v-else-if="asset === 'speaker'"><rect x="116" y="78" width="168" height="159" rx="31" fill="#61798d" /><rect x="128" y="91" width="144" height="134" rx="24" fill="#475f75" /><g v-for="r in 9" :key="r"><circle v-for="c in 12" :key="c" :cx="137+c*10" :cy="98+r*12" r="1.7" fill="#829bad" /></g><path d="M167 83h66" stroke="#b0c2d0" stroke-width="4" /></g>
    <g v-else-if="asset === 'monitor'"><rect x="53" y="56" width="294" height="172" rx="11" fill="#47566b" /><rect x="64" y="67" width="272" height="148" rx="4" fill="#a8c6e0" /><path d="m67 210 108-118 82 79 79-59v98z" fill="#83a4c3" /><path d="M200 227v23m-66 0h132" stroke="#73869e" stroke-width="12" /></g>
    <g v-else-if="asset === 'charger' || asset === 'powerbank' || asset === 'hub'"><rect x="139" y="78" width="122" height="163" rx="20" fill="#d9e1e8" stroke="#9fb0c2" stroke-width="3" /><path d="M163 91v-26m35 26v-26" stroke="#6a7c8e" stroke-width="8" /><rect x="167" y="193" width="67" height="17" rx="5" fill="#465d75" /><path d="m204 125-21 34h29l-19 28" fill="none" stroke="#7394ba" stroke-width="6" /></g>
    <g v-else-if="asset === 'stand'"><path d="m110 188 37-101h106l37 101z" fill="#c5cfd9" stroke="#91a4b8" stroke-width="4" /><path d="M144 191v48h112v-48" fill="none" stroke="#8295a9" stroke-width="8" /><path d="M127 188h146" stroke="#556f88" stroke-width="8" /></g>
    <g v-else-if="asset === 'webcam'"><rect x="110" y="97" width="180" height="93" rx="30" fill="#425568" /><circle cx="200" cy="144" r="33" fill="#8b9fb5" /><circle cx="200" cy="144" r="23" fill="#1f354e" /><circle cx="208" cy="137" r="7" fill="#a4cce7" /><path d="M166 190v31h69v-31m-88 35h106" stroke="#6a7e95" stroke-width="11" /></g>
    <g v-else-if="asset === 'basket' || asset === 'tray'"><path d="m97 114 20 120h166l20-120z" fill="#c7ac86" stroke="#a58a65" stroke-width="4" /><ellipse cx="200" cy="113" rx="104" ry="22" fill="#e4cfb0" stroke="#b59a73" stroke-width="4" /><path d="M130 136v86m35-81v85m35-82v84m35-86v85m35-91v86M115 165h171m-169 29h166" stroke="#ebd7b8" stroke-width="5" /></g>
    <g v-else-if="asset === 'clock'"><circle cx="200" cy="156" r="94" fill="#e9dfcc" stroke="#b7a281" stroke-width="6" /><circle cx="200" cy="156" r="80" fill="#fbf8ef" /><path d="M200 95v61l42 27" fill="none" stroke="#6e7d80" stroke-width="7" stroke-linecap="round" /><circle cx="200" cy="156" r="6" fill="#536971" /></g>
    <g v-else-if="asset === 'blanket' || asset === 'mat'"><path d="m84 102 207-28 35 158-207 24z" fill="#b3c4b7" stroke="#839e8d" stroke-width="3" /><path d="m118 135 169-23m-161 58 167-24m-159 57 167-24" stroke="#d9e2d8" stroke-width="9" /><path d="m119 256 6-20m15 17 6-20m15 17 6-20m15 17 6-20m15 17 6-20" stroke="#a2b7aa" stroke-width="3" /></g>
    <g v-else-if="asset === 'vase'"><path d="M174 81h52v52c74 66 58 113-26 113s-100-47-26-113z" fill="#d8c6b1" stroke="#b6a089" stroke-width="4" /><path d="M200 78V40m-1 23c-33-8-38-28-39-33 28 0 39 12 39 33m4-15c21-29 38-25 43-23-6 23-21 30-43 23" fill="#819c7d" stroke="#819c7d" stroke-width="4" /></g>
    <g v-else-if="asset === 'bottle'"><rect x="160" y="92" width="80" height="153" rx="25" fill="#9cb9ab" stroke="#688d7b" stroke-width="3" /><rect x="177" y="67" width="46" height="32" rx="8" fill="#466f60" /><path d="M182 113v100" stroke="#d4e4db" stroke-width="7" /><path d="M223 70c28-20 40 15 18 23" fill="none" stroke="#557e6a" stroke-width="5" /></g>
    <g v-else-if="asset === 'lantern'"><path d="M164 81V65a36 36 0 0 1 72 0v16" fill="none" stroke="#466b5c" stroke-width="8" /><rect x="145" y="83" width="110" height="130" rx="20" fill="#f8e9b6" stroke="#6e9480" stroke-width="7" /><rect x="135" y="207" width="130" height="33" rx="10" fill="#527c67" /><path d="M177 102v88m45-88v88" stroke="#e1c987" stroke-width="3" /></g>
    <g v-else-if="asset === 'umbrella'"><path d="M77 147a125 115 0 0 1 246 0q-31-25-60 0-31-25-62 0-31-25-62 0-31-25-62 0" fill="#779caf" stroke="#486d86" stroke-width="3" /><path d="M200 46v174c0 36 47 36 47 6" fill="none" stroke="#536f82" stroke-width="7" /></g>
    <g v-else-if="asset === 'pole'"><path d="m218 84-44 161" stroke="#9aa9b5" stroke-width="8" /><path d="m222 66-13 53" stroke="#4a5f6b" stroke-width="18" stroke-linecap="round" /><path d="m161 232 31 9" stroke="#4a5f6b" stroke-width="6" /><path d="m224 70c39 2 42 42 11 38" fill="none" stroke="#567382" stroke-width="4" /></g>
    <g v-else-if="asset === 'hat'"><path d="m143 183 15-80h84l15 80z" fill="#d7c4a2" stroke="#b49a74" stroke-width="3" /><ellipse cx="200" cy="190" rx="119" ry="36" fill="#c8b18b" /><path d="M147 164h106" stroke="#8e8469" stroke-width="15" /></g>
    <g v-else><rect x="120" y="80" width="160" height="160" rx="20" fill="#d8e5fb" /><path d="M160 160h80" stroke="#7297d6" stroke-width="8" /></g>
  </svg>
</template>
