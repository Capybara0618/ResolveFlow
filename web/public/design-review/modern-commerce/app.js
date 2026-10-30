(() => {
  'use strict';
  // Review-only state: no credentials, persistence, network requests or transaction API.
  const products = [
    { id:'headphones', name:'无线降噪耳机', store:'松间数码', category:'electronics', description:'安静听见细节。柔软耳垫与简洁轮廓，让工作和日常聆听更专注。', variants:[{name:'黑色',image:'headphones-black',price:329},{name:'银色',image:'headphones-silver',price:349}] },
    { id:'lamp', name:'桌面台灯', store:'拾光家居', category:'home', description:'柔和的光，陪你阅读和工作。简洁轮廓自然融入日常空间。', variants:[{name:'米白色',image:'lamp',price:129}] },
    { id:'keyboard', name:'机械键盘', store:'松间数码', category:'electronics', description:'利落的布局，清晰的按键反馈，让桌面保持有序。', variants:[{name:'白色',image:'keyboard-white',price:199},{name:'灰色',image:'keyboard-gray',price:219}] },
    { id:'backpack', name:'轻量双肩包', store:'轻行户外', category:'outdoor', description:'轻量轮廓与分区口袋，陪你从日常通勤走向周末出行。', variants:[{name:'深蓝色',image:'backpack-navy',price:169},{name:'橄榄绿',image:'backpack-olive',price:189}] },
    { id:'speaker', name:'蓝牙音箱', store:'松间数码', category:'electronics', description:'将喜欢的声音，带到生活的每个角落。', variants:[{name:'黑色',image:'speaker-black',price:159}] },
    { id:'cup', name:'保温杯', store:'拾光家居', category:'home', description:'随手带上一杯温暖，开始新的一天。', variants:[{name:'米白色',image:'cup',price:89}] },
    { id:'tent', name:'双人露营帐篷', store:'轻行户外', category:'outdoor', description:'带着简单的装备，去靠近山野和清晨。', variants:[{name:'橄榄绿',image:'tent',price:399}] },
    { id:'pillow', name:'棉麻靠枕', store:'拾光家居', category:'home', description:'柔软触感与自然色调，为日常留一处舒适。', variants:[{name:'米白色',image:'pillow',price:59}] },
  ];
  const state = { page:'home', product:'headphones', variant:0, quantity:1, category:'', store:'', query:'', status:'normal', added:false, tab:'details', checkoutStore:'松间数码', order:[], address:{name:'卡皮巴拉',phone:'138****0000',detail:'浙江省 杭州市 西湖区 · 桂雨路18号'}, cart:[{id:'headphones',variant:0,quantity:1,selected:true},{id:'backpack',variant:1,quantity:1,selected:true}] };
  const app = document.getElementById('app'), dialogRoot = document.getElementById('dialog-root');
  const stack = [], positions = new Map();
  let toastTimer, opener = null, oldOverflow = '';
  const escape = value => String(value).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => `¥${value.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  const photo = (v,name,cls='') => `<img class="${cls}" src="/products/v1/${v.image}.webp" alt="${escape(name)} · ${escape(v.name)}" width="1254" height="1254">`;
  const product = id => products.find(p=>p.id===id) || products[0];
  const current = () => product(state.product);
  const variant = () => current().variants[state.variant];
  const paths = {search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',cart:'<path d="M3 4h2l2.2 12h11.5l2-9H6"/><circle cx="9" cy="20" r=".8"/><circle cx="18" cy="20" r=".8"/>',store:'<path d="M4 10v10h16V10M3 10l2-6h14l2 6M9 20v-7h6v7M3 10c0 3 4 3 4 0 0 3 5 3 5 0 0 3 5 3 5 0 0 3 4 3 4 0"/>',close:'<path d="m6 6 12 12M18 6 6 18"/>',check:'<path d="m5 12 4 4L19 6"/>',bag:'<path d="M5 7h14l1 14H4L5 7ZM8 8V6a4 4 0 0 1 8 0v2"/>',address:'<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/>'};
  const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name]||paths.bag}</svg>`;
  const storeLink = name => `<button class="store-link" data-action="store" data-store="${escape(name)}">${icon('store')}${escape(name)}</button>`;
  function toast(message) { const node = document.getElementById('feedback'); clearTimeout(toastTimer); node.textContent=message; node.classList.add('visible'); toastTimer=setTimeout(()=>node.classList.remove('visible'),2400); }
  function stepper(value,action,index) { return `<div class="stepper"><button data-action="${action}" data-delta="-1" data-index="${index}" aria-label="减少数量" ${value<=1?'disabled':''}>−</button><input type="number" min="1" max="5" value="${value}" data-input="${action}" data-index="${index}" aria-label="购买数量"><button data-action="${action}" data-delta="1" data-index="${index}" aria-label="增加数量" ${value>=5?'disabled':''}>+</button></div>`; }
  function header() {
    return `<header class="site-header"><div class="header-inner"><div class="brand-wrap"><a class="brand" href="#home" data-page="home"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>ResolveFlow</a><button class="header-back" data-action="back" ${state.page==='home'?'disabled':''}>返回</button></div><form class="search" id="search-form"><input type="search" name="query" value="${escape(state.query)}" placeholder="搜索喜欢的商品" aria-label="搜索商品"><button aria-label="搜索">${icon('search')}</button></form><nav class="header-links" aria-label="商城导航"><a href="#home" data-page="home">商城</a><a href="#" data-action="support">售后咨询</a><a class="cart-link" href="#cart" data-page="cart">${icon('cart')}<span>购物车</span><span class="cart-count">${state.cart.reduce((n,r)=>n+r.quantity,0)||''}</span></a><span class="profile"><span class="avatar" aria-hidden="true">卡</span><span>卡皮巴拉</span></span></nav></div></header>`;
  }
  function categoryBar() { return `<div class="filters"><nav class="category" aria-label="商品分类">${[['','全部'],['electronics','数码'],['home','家居'],['outdoor','户外']].map(([id,label])=>`<button data-action="category" data-category="${id}" aria-pressed="${state.category===id}">${label}</button>`).join('')}</nav><select class="store-select" aria-label="选择店铺" id="store-select">${['','松间数码','拾光家居','轻行户外'].map(n=>`<option ${n===state.store?'selected':''} value="${n}">${n||'全部店铺'}</option>`).join('')}</select></div>`; }
  function filteredProducts() { return products.filter(p=>(!state.category||p.category===state.category)&&(!state.store||p.store===state.store)&&(!state.query||p.name.includes(state.query))); }
  function cards(items) { return `<div class="catalog">${items.map(p=>`<article class="product-card"><a class="product-photo" href="#product" data-action="product" data-product="${p.id}">${photo(p.variants[0],p.name)}</a><div class="product-description"><a class="product-title" href="#product" data-action="product" data-product="${p.id}">${p.name}</a><strong class="product-price">¥${p.variants[0].price}${p.variants.length>1?'<small>起</small>':''}</strong>${storeLink(p.store)}</div></article>`).join('')}</div>`; }
  function skeleton() {
    if(state.page==='home') return `<div class="catalog skeleton" role="status" aria-label="正在读取商品">${Array.from({length:8},()=>'<div><i class="photo"></i><i class="line"></i><i class="line short"></i></div>').join('')}</div>`;
    if(state.page==='product') return '<div class="skeleton skeleton-detail" role="status" aria-label="正在读取商品"><i></i><div><i class="line"></i><i class="line short"></i><i class="line"></i></div></div>';
    return '<div class="state-panel skeleton" role="status" aria-label="正在读取内容"><div class="skeleton-row"><i></i><i></i></div><div class="skeleton-row"><i></i><i></i></div></div>';
  }
  function emptyPanel(kind='empty') {
    const failed = kind==='error';
    return `<section class="empty-state">${icon(failed?'search':'bag')}<h2>${failed?'暂时没有读取成功':state.page==='cart'?'购物车还没有商品':'没有找到合适的商品'}</h2><p>${failed?'可以重新读取，刚才的选择会保留。':state.page==='cart'?'去挑选喜欢的商品吧。':'试试其他分类，或换个关键词。'}</p><button class="${failed?'secondary':'primary'}" data-action="${failed?'retry':'reset'}">${failed?'重新读取':state.page==='cart'?'去逛商城':'查看全部商品'}</button></section>`;
  }
  function home() {
    const list=filteredProducts();
    return `<section class="hero"><div><h1>把喜欢的好物，<br>带进日常。</h1><button class="primary" data-action="browse">浏览好物</button></div></section><section id="catalog"><div class="catalog-heading"><h2>${state.query?`“${escape(state.query)}”的搜索结果`:state.store?escape(state.store):'精选好物'}</h2>${categoryBar()}</div>${state.status==='loading'?skeleton():state.status==='error'?emptyPanel('error'):state.status==='empty'||!list.length?emptyPanel():cards(list)}</section>`;
  }
  function productPage() {
    if(state.status!=='normal') return state.status==='loading'?skeleton():emptyPanel(state.status);
    const p=current(),v=variant();
    return `<section class="product-layout"><div><div class="gallery-main">${photo(v,p.name)}</div><div class="thumbnails" aria-label="商品图片">${p.variants.map((x,i)=>`<button data-action="variant" data-variant="${i}" aria-label="查看${x.name}商品图片" aria-pressed="${state.variant===i}">${photo(x,p.name)}</button>`).join('')}</div></div><div class="product-info">${storeLink(p.store)}<h1>${p.name}</h1><p class="description">${p.description}</p><strong class="detail-price"><small>¥</small>${v.price.toFixed(2)}</strong><p class="variant-label">颜色<span>${v.name}</span></p><div class="variants">${p.variants.map((x,i)=>`<button data-action="variant" data-variant="${i}" aria-pressed="${state.variant===i}">${x.name}</button>`).join('')}</div><div class="quantity-label">数量${stepper(state.quantity,'quantity','')}</div><div class="buy-actions"><button class="primary" data-action="buy">立即购买</button><button class="secondary" data-action="add">加入购物车</button></div><div class="added-slot" aria-live="polite">${state.added?`${icon('check')}已加入购物车<button class="text-link" data-page="cart">查看购物车</button>`:''}</div></div></section><section class="details-section"><div class="section-tabs"><button data-action="tab" data-tab="details" aria-pressed="${state.tab==='details'}">商品信息</button><button data-action="tab" data-tab="reviews" aria-pressed="${state.tab==='reviews'}">买家评价</button></div>${state.tab==='details'?`<dl class="specifications"><div><dt>商品名称</dt><dd>${p.name}</dd></div><div><dt>颜色</dt><dd>${p.variants.map(x=>x.name).join(' / ')}</dd></div><div><dt>店铺</dt><dd>${p.store}</dd></div><div><dt>当前款式</dt><dd>${v.name}</dd></div></dl>`:`<article class="review-entry"><header><strong>卡皮巴拉</strong><span class="muted">已购 · ${v.name}</span></header><p>图片和实物颜色一致，日常用起来很顺手。包装完整，整体很喜欢。</p><time>10月30日</time></article>`}</section>`;
  }
  const eligibleRows = store => state.cart.filter(r=>r.selected&&product(r.id).store===store);
  const lineAmount = r => product(r.id).variants[r.variant].price*r.quantity;
  function summary(lines,checkout=false) {
    const total=lines.reduce((n,r)=>n+lineAmount(r),0),count=lines.reduce((n,r)=>n+r.quantity,0);
    const stores=[...new Set(state.cart.map(r=>product(r.id).store))];
    return `<aside class="summary"><h2>${checkout?'订单金额':'结算'}</h2>${!checkout&&stores.length>1?`<div class="store-choices" aria-label="结算店铺">${stores.map(s=>`<button data-action="checkout-store" data-store="${s}" aria-pressed="${s===state.checkoutStore}">${icon('store')}${s}</button>`).join('')}</div>`:''}<dl><div><dt>商品数量</dt><dd>${count} 件</dd></div><div><dt>商品金额</dt><dd>${money(total)}</dd></div></dl><div class="summary-total"><span>合计</span><strong>${money(total)}</strong></div><button class="primary" data-action="${checkout?'submit-order':'checkout'}" ${!lines.length?'disabled':''}>${checkout?'提交订单':'确认结算'}</button>${!checkout?`<p class="summary-caption">${state.checkoutStore}</p>`:''}</aside>`;
  }
  function cart() {
    if(state.status!=='normal') return `<div class="heading"><h1>购物车</h1></div>${state.status==='loading'?skeleton():emptyPanel(state.status)}`;
    if(!state.cart.length) return '<div class="heading"><h1>购物车</h1></div>'+emptyPanel();
    const stores=[...new Set(state.cart.map(r=>product(r.id).store))];
    if(!stores.includes(state.checkoutStore)) state.checkoutStore=stores[0];
    return `<div class="heading"><h1>购物车<span>${state.cart.length} 件商品</span></h1><button class="text-link" data-page="home">继续挑选</button></div><div class="cart-layout"><div class="cart-groups">${stores.map(s=>`<section class="cart-group"><header>${icon('store')}<strong>${s}</strong></header>${state.cart.map((r,i)=>({r,i})).filter(({r})=>product(r.id).store===s).map(({r,i})=>{const p=product(r.id),v=p.variants[r.variant];return `<article class="cart-row"><input type="checkbox" data-input="selected" data-index="${i}" aria-label="选择${p.name}" ${r.selected?'checked':''}><a class="cart-thumb" href="#product" data-action="product" data-product="${p.id}">${photo(v,p.name)}</a><div class="cart-copy"><h3><a href="#product" data-action="product" data-product="${p.id}">${p.name}</a></h3><p>${v.name}</p>${stepper(r.quantity,'cart-quantity',i)}</div><div class="row-price"><strong>${money(lineAmount(r))}</strong><button data-action="remove" data-index="${i}">移除</button></div></article>`;}).join('')}</section>`).join('')}</div>${summary(eligibleRows(state.checkoutStore))}</div>`;
  }
  function checkout() {
    if(state.status!=='normal') return `<div class="heading"><h1>确认订单</h1></div>${state.status==='loading'?skeleton():emptyPanel(state.status)}`;
    const lines=state.order.length?state.order:eligibleRows(state.checkoutStore);
    return `<div class="heading"><h1>确认订单</h1></div><div class="checkout-layout"><div class="checkout-main"><section class="checkout-section"><header><h2>收货信息</h2><button class="text-link" data-action="edit-address">修改</button></header><div class="address"><div><strong>${escape(state.address.name)}</strong><span>${escape(state.address.phone)}</span></div><p>${escape(state.address.detail)}</p></div></section><section class="checkout-section"><header><h2>商品清单</h2></header><p class="checkout-store">${icon('store')}${lines.length?product(lines[0].id).store:state.checkoutStore}</p>${lines.map(r=>{const p=product(r.id),v=p.variants[r.variant];return `<div class="checkout-product">${photo(v,p.name)}<div><h3>${p.name}</h3><p>${v.name} · 数量 ${r.quantity}</p></div><strong>${money(lineAmount(r))}</strong></div>`;}).join('')}</section></div>${summary(lines,true)}</div>`;
  }
  function render() {
    app.innerHTML=header()+`<main class="page" data-view="${state.page}">${({home,product:productPage,cart,checkout})[state.page]()}</main>`;
    document.querySelectorAll('[data-page]').forEach(b=>b.setAttribute('aria-current',b.dataset.page===state.page?'page':'false'));
    document.getElementById('review-state').value=state.status;
  }
  function remember() { positions.set(state.page,scrollY); }
  function go(page,push=true) {
    if(!['home','product','cart','checkout'].includes(page))return;
    remember();if(push&&state.page!==page)stack.push(state.page);
    state.page=page;state.status='normal';state.added=false;render();window.scrollTo({top:0,behavior:'auto'});
    document.querySelector('main')?.setAttribute('tabindex','-1');document.querySelector('main')?.focus({preventScroll:true});
  }
  function back() { const page=stack.pop()||'home';go(page,false);window.scrollTo({top:positions.get(page)||0,behavior:'auto'}); }
  function closeDialog() { dialogRoot.innerHTML='';document.body.style.overflow=oldOverflow;if(opener?.isConnected)opener.focus({preventScroll:true});opener=null; }
  function dialog(title,body,footer) {
    opener=document.activeElement;oldOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
    dialogRoot.innerHTML=`<div class="dialog-backdrop"><section class="dialog" role="dialog" aria-modal="true" aria-label="${title}" tabindex="-1"><header><h2>${title}</h2><button class="dialog-close" data-action="close" aria-label="关闭弹窗">${icon('close')}</button></header>${body}<footer>${footer}</footer></section></div>`;
    dialogRoot.querySelector('[role=dialog]').focus({preventScroll:true});
  }
  function checkoutLines(lines) { if(!lines.length)return;state.order=lines.map(r=>({...r}));go('checkout'); }
  function handleAction(button) {
    const action=button.dataset.action;
    if(button.dataset.page){if(button.dataset.page==='checkout')state.order=eligibleRows(state.checkoutStore).map(r=>({...r}));go(button.dataset.page);return;}
    if(action==='product'){const id=button.dataset.product;if(id!==state.product){state.product=id;state.variant=0;state.quantity=1;}go('product');}
    else if(action==='back')back();
    else if(action==='browse')document.getElementById('catalog')?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth'});
    else if(action==='category'){state.category=button.dataset.category;render();}
    else if(action==='store'){state.store=button.dataset.store;state.category='';state.query='';go('home');}
    else if(action==='variant'){state.variant=Number(button.dataset.variant);state.added=false;render();}
    else if(action==='tab'){state.tab=button.dataset.tab;render();}
    else if(action==='quantity'){state.quantity=Math.max(1,Math.min(5,state.quantity+Number(button.dataset.delta)));state.added=false;render();}
    else if(action==='add'){
      const row=state.cart.find(r=>r.id===state.product&&r.variant===state.variant);
      if(row&&row.quantity+state.quantity>5){toast('购物车中这款商品已达到数量上限');return;}
      if(row){row.quantity+=state.quantity;row.selected=true;}else state.cart.push({id:state.product,variant:state.variant,quantity:state.quantity,selected:true});
      state.added=true;render();toast('已加入购物车');
    }
    else if(action==='cart-quantity'){const r=state.cart[Number(button.dataset.index)];if(r){r.quantity=Math.max(1,Math.min(5,r.quantity+Number(button.dataset.delta)));render();}}
    else if(action==='checkout-store'){state.checkoutStore=button.dataset.store;render();}
    else if(action==='checkout')checkoutLines(eligibleRows(state.checkoutStore));
    else if(action==='buy')checkoutLines([{id:state.product,variant:state.variant,quantity:state.quantity,selected:true}]);
    else if(action==='remove'){const index=Number(button.dataset.index);dialog('移除这件商品？',`<p>${escape(product(state.cart[index].id).name)}将从购物车移除。</p>`,`<button class="secondary" data-action="close">保留商品</button><button class="danger" data-action="confirm-remove" data-index="${index}">移除商品</button>`);}
    else if(action==='confirm-remove'){state.cart.splice(Number(button.dataset.index),1);closeDialog();render();toast('已移除商品');}
    else if(action==='close')closeDialog();
    else if(action==='edit-address')dialog('收货信息',`<form id="address-form"><label>收货人<input name="name" value="${escape(state.address.name)}" required maxlength="40"></label><label>联系电话<input name="phone" value="${escape(state.address.phone)}" required maxlength="32"></label><label>详细地址<input name="detail" value="${escape(state.address.detail)}" required maxlength="200"></label></form>`,`<button class="secondary" data-action="close">取消</button><button class="primary" form="address-form" type="submit">保存地址</button>`);
    else if(action==='submit-order')dialog('订单已提交','<p>可以在“我的订单”查看处理进度。</p>','<button class="primary" data-action="finish">返回商城</button>');
    else if(action==='finish'){closeDialog();stack.length=0;go('home',false);}
    else if(action==='retry'){state.status='normal';render();toast('内容已更新');}
    else if(action==='reset'){state.query='';state.category='';state.store='';go('home');}
    else if(action==='support')toast('本次样板先审查商城购买流程，助手在后续模块打磨');
  }
  document.addEventListener('click',event=>{
    if(event.target.classList.contains('dialog-backdrop')){closeDialog();return;}
    const button=event.target.closest('[data-action],[data-page]');if(!button||button.disabled)return;
    event.preventDefault();handleAction(button);
  });
  document.addEventListener('change',event=>{
    const el=event.target;
    if(el.id==='review-state'){state.status=el.value;render();}
    else if(el.id==='store-select'){state.store=el.value;render();}
    else if(el.dataset.input==='selected'){const r=state.cart[Number(el.dataset.index)];if(r){r.selected=el.checked;render();}}
    else if(el.dataset.input==='quantity'||el.dataset.input==='cart-quantity'){
      const value=Number(el.value);if(!Number.isInteger(value)||value<1||value>5){toast('请选择1至5件商品');render();return;}
      if(el.dataset.input==='quantity'){state.quantity=value;state.added=false;}else state.cart[Number(el.dataset.index)].quantity=value;
      render();
    }
  });
  document.addEventListener('submit',event=>{
    if(event.target.id==='search-form'){event.preventDefault();state.query=new FormData(event.target).get('query').trim();go('home');document.getElementById('catalog')?.scrollIntoView({block:'start'});}
    if(event.target.id==='address-form'){event.preventDefault();const data=new FormData(event.target);state.address={name:data.get('name').trim(),phone:data.get('phone').trim(),detail:data.get('detail').trim()};closeDialog();render();toast('地址已保存');}
  });
  document.addEventListener('keydown',event=>{
    const panel=dialogRoot.querySelector('[role=dialog]');if(!panel)return;
    if(event.key==='Escape'){event.preventDefault();closeDialog();return;}
    if(event.key==='Tab'){const items=[...panel.querySelectorAll('button:not(:disabled),input:not(:disabled)')];const first=items[0],last=items.at(-1);if(event.shiftKey&&(document.activeElement===first||document.activeElement===panel)){event.preventDefault();last?.focus();}else if(!event.shiftKey&&(document.activeElement===last||document.activeElement===panel)){event.preventDefault();first?.focus();}}
  });
  render();
})();
