const {chromium}=require('playwright');
const fs=require('fs'); const path=require('path'); const {pathToFileURL}=require('url');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.CUSTOMER_PREVIEW_BROWSER||'msedge'}); try { const page=await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error('PAGE ERROR:',e.message)});page.on('console',m=>{if(m.type()==='error')console.error('CONSOLE:',m.text())});
 const base=pathToFileURL(path.resolve('docs/ui-customer-agent-v1/index.html')).href;
 const views=['orders','chat','handoff','refund','progress','queue','detail'];
 fs.mkdirSync('docs/ui-customer-agent-v1/images',{recursive:true}); const results=[];
 for(const view of views){await page.goto(base+'?screen='+view+'#'+view);await page.locator('[data-view="'+view+'"][aria-pressed="true"]').waitFor();await page.evaluate(()=>document.fonts.ready);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow)throw Error('overflow '+view);
  await page.screenshot({path:'docs/ui-customer-agent-v1/images/'+view+'.png',fullPage:true});results.push({view,width:1440,overflow});}
 for(const width of [1280,1680]){await page.setViewportSize({width,height:1050});for(const view of views){await page.goto(base+'?screen='+view+'#'+view);await page.locator('[data-view="'+view+'"][aria-pressed="true"]').waitFor();if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('overflow '+view+'@'+width);results.push({view,width,overflow:false});}}
 await page.setViewportSize({width:1440,height:1050});await page.goto(base+'#orders');await page.locator('[data-action="select"][data-sample="A-SIGNED"]').click();
 await page.locator('[data-view="handoff"]').first().click();await page.locator('[data-action="confirm-handoff"]').click();
 if(!(await page.locator('.chat-title .pill').innerText()).includes('等待'))throw Error('handoff');
 await page.locator('[data-recipient="assistant"]').click();if(!(await page.locator('#message-input').getAttribute('placeholder')).includes('描述问题'))throw Error('recipient');
 await page.locator('[data-action="policy"]').first().click();if(!(await page.locator('#policy').innerText()).includes('松间数码'))throw Error('policy store');await page.keyboard.press('Escape');
 await page.locator('[data-action="select"][data-sample="B-SIGNED"]').click();if(!(await page.locator('.chat-title').innerText()).includes('拾光家居'))throw Error('switch merchant');
 await page.locator('#message-input').fill('台灯专属补充');await page.locator('[data-action="send"]').click();
 await page.locator('[data-action="select"][data-sample="A-SIGNED"]').click();if((await page.locator('.chat-body').innerText()).includes('台灯专属补充'))throw Error('context leaked');
 await page.locator('[data-view="refund"]').first().click();await page.locator('[data-action="cancel"]').click();if(!(await page.locator('.chat-title .pill').innerText()).includes('智能客服'))throw Error('cancel creates application');
 await page.locator('[data-view="refund"]').first().click();await page.locator('[data-action="confirm-refund"]').click();
 if(!(await page.locator('.chat-title .pill').innerText()).includes('待核验'))throw Error('refund state');
 if((await page.locator('.chat-body').innerText()).includes('没有申请退款'))throw Error('mixed consultation refund');
 await page.locator('[data-view="handoff"]').first().click();await page.locator('#summary').fill('只核实签收记录，不退款');await page.locator('#share').uncheck();await page.locator('[data-action="confirm-handoff"]').click();
 await page.locator('[data-view="detail"]').first().click();if(!(await page.locator('.detail-grid .card:nth-of-type(2)>p').first().innerText()).includes('只核实签收记录，不退款'))throw Error('edited summary ignored');if(!(await page.locator('.evidence').innerText()).includes('未共享'))throw Error('share preview ignored');
 await page.locator('#merchant-reply').fill('商家已收到本次问题，请补充代收授权情况。');await page.locator('[data-action="merchant-reply"]').first().click();
 await page.locator('[data-view="progress"]').first().click();if(!(await page.locator('.chat-body').innerText()).includes('商家已收到本次问题'))throw Error('merchant reply not shown');
 await page.locator('[data-recipient="merchant"]').click();await page.locator('#message-input').fill('我没有授权他人代收。');await page.locator('[data-action="send"]').click();
 if(!(await page.locator('.chat-body').innerText()).includes('已补充到当前商家核查记录'))throw Error('supplement not routed');
 await page.locator('[data-action="resolved"]').click();if(!(await page.locator('.chat-title .pill').innerText()).includes('已解决'))throw Error('resolution');
 await page.locator('[data-view="orders"]').first().click();await page.locator('[data-action="select"][data-sample="A-TRANSIT"]').click();await page.locator('[data-view="handoff"]').first().click();
 if((await page.locator('#summary').inputValue()).includes('签收'))throw Error('transit changed to signed');
 if(!(await page.locator('.context').innerText()).includes('IN_TRANSIT'))throw Error('policy not scoped to logistics state');
 if(errors.length)throw Error(errors.join('\n'));
 fs.writeFileSync('reports/customer-agent-design-v1/preview-check.json',JSON.stringify({prototype_only:true,views:results,checks:['handoff preview and submission','recipient switching','policy drawer','merchant switch','independent notes','cancel before confirmation','refund confirmation and pending review','consultation vs refund distinction','edited handoff summary','shared original text choice','merchant reply delivery','supplement routing','customer resolution','transit handoff keeps selected order and applicable rule'],browser_errors:errors},null,2)+'\n');
 console.log('21 view/width checks + 14 interactions passed; 7 screenshots'); } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
