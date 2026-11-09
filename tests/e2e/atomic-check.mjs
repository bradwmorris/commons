// Real schema-10 UI journeys against an explicitly owned synthetic installation.
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
const state=JSON.parse(fs.readFileSync(process.env.COMMONS_ATOMIC_FIXTURE,'utf8'));
const results=process.env.COMMONS_ATOMIC_RESULTS;
const browser=await chromium.launch({headless:true,executablePath:process.env.COMMONS_CHROMIUM_BINARY});
const page=await browser.newPage({viewport:{width:1280,height:800},extraHTTPHeaders:{Origin:state.origin}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const checks=[];
try {
 await page.goto(state.origin);await page.getByLabel('Username',{exact:true}).fill('alice');await page.getByLabel('Password',{exact:true}).fill(state.password);await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByRole('navigation')).toBeVisible();await expect(page.locator('.record').first()).toBeVisible();
 let metrics=await page.locator('.record').first().evaluate(e=>({height:e.getBoundingClientRect().height,nowrap:getComputedStyle(e.querySelector('strong')).whiteSpace}));expect(metrics.height).toBe(50);expect(metrics.nowrap).toBe('nowrap');checks.push('desktop-single-line-50px');
 await page.screenshot({path:results+'/atomic-objects-loaded.png'});
 await expect(page.getByRole('button',{name:'Memories',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'Evals',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Users',exact:true}).first().click();await expect(page.getByRole('link',{name:'Open Alice Synthetic'})).toBeVisible();await page.getByRole('link',{name:'Open Alice Synthetic'}).click();await expect(page.getByRole('heading',{name:'Alice Synthetic'})).toBeVisible();checks.push('dedicated-user-list-and-detail');
 await page.getByRole('button',{name:'Tasks',exact:true}).first().click();await page.getByRole('link',{name:'Open Synthetic task',exact:true}).first().click();await expect(page.getByRole('button',{name:'Edit Task body',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Edit Task body',exact:true}).click();await page.getByRole('textbox',{name:'Task body',exact:true}).fill('Updated supporting task detail.');await page.getByRole('button',{name:'Save Task body',exact:true}).click();await expect(page.getByRole('textbox',{name:'Task body',exact:true})).toHaveValue('Updated supporting task detail.');checks.push('canonical-body-inline-save');
 await page.getByRole('textbox',{name:'Task body',exact:true}).fill('Supporting detail. '.repeat(1500));await page.getByRole('button',{name:'Save Task body',exact:true}).click();await expect(page.locator('.task-brief-editor .inline-editor-status')).toContainText('500');await expect(page.getByRole('textbox',{name:'Task body',exact:true})).toHaveValue('Supporting detail. '.repeat(1500));checks.push('oversize-rejection-preserves-draft');
 await page.getByRole('textbox',{name:'Task body',exact:true}).press('Escape');
 const avatars=page.locator('.detail-object-id .attribution-stack');await expect(avatars).toBeVisible();
 await expect(avatars.locator('[title]')).toHaveCount(0);expect(await avatars.innerText()).not.toContain('Alice');
 const properties=page.getByRole('region',{name:'Task properties'});
 await expect(properties.locator('select,input,button,textarea,summary,[contenteditable="true"]')).toHaveCount(0);
 for(const label of ['Status','Assigned to','Due','Priority','Project','Work type']) await expect(properties.getByText(label,{exact:true})).toBeVisible();
 expect(await avatars.locator('.user-avatar').first().evaluate(e=>e.getBoundingClientRect().width)).toBe(34);
 expect(await properties.locator('.user-avatar').first().evaluate(e=>e.getBoundingClientRect().width)).toBe(36);
 await expect(page.locator('.task-assignee[title],.user-avatar[title],.attribution-stack [title]')).toHaveCount(0);
 await page.screenshot({path:results+'/atomic-attribution-detail.png'});checks.push('larger-accessible-avatars-and-read-only-task-properties');

 await page.getByRole('button',{name:'Schema',exact:true}).first().click();await expect(page.getByRole('region',{name:'Installed schema'})).toBeVisible();await expect(page.getByText('Installed schema 12 · 10 tables',{exact:true})).toBeVisible();await expect(page.getByRole('table',{name:'objects columns'}).locator('tbody tr')).toHaveCount(9);
 await page.getByRole('navigation',{name:'Schema tables'}).locator('a[href="/schema/users"]').click();await expect(page).toHaveURL(/\/schema\/users$/);await page.reload();await expect(page.getByRole('navigation',{name:'Schema tables'}).locator('a[href="/schema/users"]')).toHaveAttribute('aria-current','page');await page.screenshot({path:results+'/atomic-schema-loaded.png'});checks.push('installed-schema-table-navigation-and-reload');
 await page.getByRole('button',{name:'Objects',exact:true}).first().click();await expect(page.locator('.record').first()).toBeVisible();await page.setViewportSize({width:390,height:844});await expect(page.locator('.record').first()).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);expect(await page.locator('.record').first().evaluate(e=>e.getBoundingClientRect().height)).toBe(46);await page.screenshot({path:results+'/atomic-objects-narrow.png'});checks.push('narrow-single-line-no-overflow');

 await page.setViewportSize({width:1280,height:800});
 const deletionResponse=await page.request.post(state.origin+'/api/apply',{data:{contract_version:'commons/0.1',idempotency_key:'browser-delete-'+crypto.randomUUID(),operations:[{op:'create_object',local_ref:'fixture',kind:'note',title:'Synthetic deletion UI fixture',description:'A note for the deletion interaction.',body:'Synthetic removable content.',fields:{}}]}});
 expect(deletionResponse.ok(),await deletionResponse.text()).toBe(true);const deletionId=(await deletionResponse.json()).local_refs.fixture;
 await page.goto(state.origin+'/notes/'+deletionId);await page.getByRole('button',{name:'Delete Object',exact:true}).click();
 await expect(page.getByRole('dialog')).toContainText('Connected independent records survive');await page.screenshot({path:results+'/ordinary-delete-confirm.png',animations:'disabled'});
 await page.getByRole('button',{name:'Cancel',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);expect((await page.request.get(state.origin+'/api/objects/'+deletionId)).status()).toBe(200);
 await page.getByRole('button',{name:'Delete Object',exact:true}).click();await page.getByRole('button',{name:'Confirm deletion',exact:true}).click();await expect(page).toHaveURL(/\/notes$/);expect((await page.request.get(state.origin+'/api/objects/'+deletionId)).status()).toBe(410);checks.push('ordinary-object-delete-cancel-confirm-readback');

 const threadId=crypto.randomUUID();
 const captureResponse=await page.request.post(state.origin+'/api/capture',{data:{contract_version:'commons.capture/1',source:{provider:'Synthetic',namespace:'browser-search',thread_id:threadId},chat_id:threadId,batch_id:'first',title:'Synthetic searchable conversation',coverage:{status:'partial',messages:'visible',tools:'visible',attachments:'none',history:'current',gaps:[]},items:[{id:crypto.randomUUID(),source_item_id:'body',position:0,kind:'message',role:'human',body:'Browserconversationneedle only in this visible message.'}],runs:[]}});expect(captureResponse.ok(),await captureResponse.text()).toBe(true);
 await page.goto(state.origin+'/threads');await page.getByRole('textbox',{name:'Search conversations',exact:true}).fill('Browserconversationneedle');await page.getByRole('button',{name:'Search stored text',exact:true}).click();
 const search=page.getByRole('region',{name:'Conversation search',exact:true});await expect(search.getByRole('link',{name:'Synthetic searchable conversation',exact:true})).toBeVisible();await search.getByRole('button',{name:'Read matching text',exact:true}).click();await expect(page.getByRole('region',{name:'Matching conversation text',exact:true})).toContainText('Browserconversationneedle only in this visible message.');await page.screenshot({path:results+'/conversation-search-window.png'});
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await search.getByRole('button',{name:'Search stored text',exact:true}).scrollIntoViewIfNeeded();await expect(search.getByRole('button',{name:'Search stored text',exact:true})).toBeInViewport();await page.screenshot({path:results+'/conversation-search-narrow.png'});checks.push('conversation-message-only-search-and-exact-window-desktop-narrow');
 expect(errors).toEqual([]);fs.writeFileSync(results+'/atomic-browser-result.json',JSON.stringify({passed:true,checks,metrics},null,2));
 console.log('Passed:',checks.join(', '));
} catch(e) {await page.screenshot({path:results+'/atomic-browser-failure.png'});fs.writeFileSync(results+'/atomic-browser-result.json',JSON.stringify({passed:false,checks,error:String(e),pageErrors:errors},null,2));throw e;} finally{await browser.close();}

await import('./telemetry-check.mjs');
