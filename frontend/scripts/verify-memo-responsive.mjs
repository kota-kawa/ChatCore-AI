// Usage: node scripts/verify-memo-responsive.mjs <playwright-core/index.mjs> <chromium executable> [base URL] [output directory]
// Uses isolated browser contexts and mocked APIs; no real account, database, or LLM request is made.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [playwrightPath, executablePath, baseUrl = 'http://127.0.0.1:3100', output = '/tmp/chatcore-memo-visual'] = process.argv.slice(2);
assert(playwrightPath && executablePath, 'Pass a Playwright module path and matching Chromium executable.');
const { chromium } = await import(pathToFileURL(path.resolve(playwrightPath)).href);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath, args: ['--no-sandbox', '--disable-gpu'] });
const results = [];
const longCollection = '仕事・企画の打ち合わせと引き継ぎ事項をまとめた長いコレクション名';
const longBody = Array.from({ length: 24 }, (_, i) => `## 手順 ${i + 1}\n\n毎日の予定を確認しながら、必要な作業を整理します。\n\n- [ ] 作業を確認する`).join('\n\n');

async function installFixture(context) {
  let nextId = 90;
  const writes = [];
  const memos = Array.from({ length: 12 }, (_, i) => ({
    id: i + 1,
    title: i === 0 ? '週末の買い物と家事のメモ' : i === 1 ? '仕事の引き継ぎと今週の打ち合わせで確認することについての詳しいメモ' : `作業メモ ${i + 1}`,
    ai_response: i === 0 ? longBody : '今日の予定と必要な作業を確認します。',
    excerpt: '今日の予定についてのメモ。買い物・家事・仕事の手順を整理しています。',
    collection_id: 1, collection_name: '日々の記録', collection_color: '#5c73c8',
    is_pinned: i < 2, is_archived: false, background_color: null,
    created_at: '2026-10-05T09:00:00+09:00', updated_at: '2026-10-06T09:00:00+09:00',
  }));
  const collections = [{ id: 1, name: '日々の記録', color: '#5c73c8', memo_count: 12 }, { id: 2, name: longCollection, color: '#9a8f65', memo_count: 0 }];
  await context.route(/\/(?:api|memo\/api|prompt_manage\/api)(?:\/|\?|$)/, async route => {
    const req = route.request(), url = new URL(req.url()), endpoint = url.pathname;
    const input = req.postData() ? req.postDataJSON() : {};
    if (req.method() !== 'GET') writes.push({ endpoint, method: req.method(), input });
    let payload = {};
    if (endpoint === '/api/current_user') payload = { logged_in: true, user: { id: 99999, username: '画面検証', preferred_locale: 'ja' } };
    else if (endpoint === '/api/csrf-token') payload = { csrf_token: 'ui-verification' };
    else if (endpoint === '/api/ai-agent') {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: `data: ${JSON.stringify({ type: 'done', response: '検証用の応答です。', model: 'UI fixture' })}\n\n` });
      return;
    } else if (endpoint === '/memo/api/collections') {
      if (req.method() === 'POST') collections.push({ id: ++nextId, ...input, memo_count: 0 });
      payload = { collections };
    } else if (endpoint === '/memo/api/recent') {
      const q = url.searchParams.get('q') ?? '';
      const visible = memos.filter(m => !m.deleted_at && (!q || m.title.includes(q) || m.ai_response.includes(q)) &&
        (!url.searchParams.has('collection_id') || String(m.collection_id) === url.searchParams.get('collection_id')));
      payload = { memos: url.searchParams.has('only_trashed') || url.searchParams.has('only_archived') ? [] : visible, total: visible.length };
    } else if (endpoint === '/memo/api' && req.method() === 'POST') {
      memos.unshift({ ...memos[0], ...input, id: ++nextId, excerpt: input.ai_response, is_pinned: false });
      payload = { memo: memos[0] };
    } else if (/^\/memo\/api\/\d+$/.test(endpoint)) {
      const memo = memos.find(m => m.id === Number(endpoint.split('/').at(-1)));
      if (req.method() === 'PATCH') {
        Object.assign(memo, input);
        if (input.clear_background_color) memo.background_color = null;
        if (input.clear_collection) memo.collection_id = null;
        const collection = collections.find(c => c.id === memo.collection_id);
        memo.collection_name = collection?.name ?? null;
        memo.collection_color = collection?.color ?? null;
      }
      payload = { memo };
    } else if (/\/memo\/api\/\d+\/share$/.test(endpoint)) {
      payload = { share_url: `${baseUrl}/shared/memo/ui-verification`, is_active: true, expires_at: '2026-11-05T09:00:00+09:00' };
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  return { writes, memos, collections };
}

async function screenshot(page, profile, label) {
  const file = `${profile}-${label}.png`;
  await page.waitForTimeout(400);
  const visibleHeight = await page.evaluate(() => Math.min(innerHeight, window.visualViewport?.height ?? innerHeight));
  await page.screenshot({ path: path.join(output, file), clip: { x: 0, y: 0, width: page.viewportSize().width, height: visibleHeight } });
  return file;
}

async function visibleRect(locator, visibleHeight, label, viewportTop = 0) {
  const r = await locator.boundingBox();
  assert(r && r.width > 0 && r.height > 0, `${label}: missing visible target`);
  assert(r.y >= viewportTop - 1 && r.y + r.height <= viewportTop + visibleHeight + 1, `${label}: outside visual viewport ${JSON.stringify(r)}`);
  return r;
}

async function iconTargets(page) {
  const icons = await page.locator('button').evaluateAll(elements => elements.flatMap(element => {
    const rect = element.getBoundingClientRect();
    const root = element.getRootNode();
    if (root instanceof ShadowRoot && root.host.tagName === 'NEXTJS-PORTAL') return [];
    if (element.innerText.trim() || rect.width === 0 || rect.height === 0 || element.closest('[hidden], [aria-hidden="true"]')) return [];
    return [{ label: element.getAttribute('aria-label'), className: element.className, width: rect.width, height: rect.height }];
  }));
  assert.deepEqual(icons.filter(icon => icon.width < 43.9 || icon.height < 43.9), [], 'Icon targets must be at least 44x44 pixels');
  return icons;
}

function contrastRatio(foreground, background) {
  const luminance = color => {
    const values = color.match(/[\d.]+/g).slice(0, 3).map(Number).map(v => v / 255);
    const linear = values.map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
  };
  const f = luminance(foreground), b = luminance(background);
  return (Math.max(f, b) + 0.05) / (Math.min(f, b) + 0.05);
}

async function clickNavForVerification(page) {
  await page.locator('action-menu').locator('.btn--menu').tap();
}

async function iosViewport(page, height) {
  await page.evaluate(h => {
    window.__memoVerificationHeight = h;
    Object.defineProperty(window.visualViewport, 'height', { configurable: true, get: () => window.__memoVerificationHeight });
    window.visualViewport.dispatchEvent(new Event('resize'));
  }, height);
  await page.waitForTimeout(200);
}

try {
  for (const [width, theme] of [[320, 'light'], [360, 'dark'], [390, 'light'], [390, 'dark'], [768, 'light'], [769, 'dark'], [1024, 'light'], [1024, 'dark'], [1366, 'light'], [1366, 'dark']]) {
    const mobile = width <= 768, height = mobile ? 740 : 768;
    const profile = `${width}-${theme}`;
    const context = await browser.newContext({ viewport: { width, height }, isMobile: mobile, hasTouch: mobile, locale: 'ja-JP', timezoneId: 'Asia/Tokyo' });
    const fixture = await installFixture(context);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${baseUrl}/memo`);
    await page.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
    await page.waitForFunction(() => document.querySelector('.memo-toolbar__count')?.textContent === '12件');
    await page.evaluate(t => document.documentElement.setAttribute('data-theme', t), theme);
    await page.waitForTimeout(600);
    const list = await page.evaluate(() => {
      const badge = document.querySelector('.memo-collection-badge'), style = getComputedStyle(badge);
      return { scrollWidth: document.documentElement.scrollWidth, width: innerWidth, columns: getComputedStyle(document.querySelector('.memo-history__list')).columnCount,
        badgeColor: style.color, badgeBackground: style.backgroundColor, card: document.querySelector('.memo-item').getBoundingClientRect().toJSON() };
    });
    assert(list.scrollWidth <= width + 1, `${profile}: page horizontal overflow`);
    if (mobile) assert.equal(list.columns, '1');
    list.badgeContrast = contrastRatio(list.badgeColor, list.badgeBackground);
    assert(list.badgeContrast >= 4.5, 'Collection badge text must remain readable');
    list.iconTargets = await iconTargets(page);
    if (mobile) {
      const nav = await page.locator('action-menu').locator('.actions-menu').boundingBox();
      const toolbar = await page.locator('.memo-toolbar').boundingBox();
      assert(nav && toolbar && nav.y >= toolbar.y && nav.y + nav.height <= toolbar.y + toolbar.height, 'Navigation must be in the toolbar, clear of cards');
      const navOnTop = await page.locator('action-menu').evaluate(host => {
        const button = host.shadowRoot.querySelector('.btn--menu'), rect = button.getBoundingClientRect();
        return document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2) === host;
      });
      assert(navOnTop, 'Navigation must be the topmost hit target in the toolbar');
      const agent = await page.locator('.global-ai-agent-button').boundingBox();
      assert(agent && agent.y >= toolbar.y && agent.y + agent.height <= toolbar.y + toolbar.height, 'Global support must be clear of cards');
      await clickNavForVerification(page);
      assert(await page.locator('action-menu').locator('#actionMenuButton').isChecked());
      await clickNavForVerification(page);
    }
    await screenshot(page, profile, 'list');
    const click = locator => mobile ? locator.tap() : locator.click();
    const postCount = () => fixture.writes.filter(w => w.endpoint === '/memo/api').length;
    const before = postCount();
    await click(page.getByRole('button', { name: 'テキストメモを作成', exact: true }));
    const content = page.getByRole('textbox', { name: '本文', exact: true });
    await content.waitFor({ state: 'visible' });
    assert.equal(postCount(), before, 'Opening text capture must not save');
    await content.fill(longBody);
    if (mobile) {
      await iosViewport(page, 420);
      await visibleRect(content, 420, 'new memo body');
      await visibleRect(page.locator('.memo-compose-mobile-modal.is-open .memo-format-toolbar'), 420, 'format toolbar');
      const nav = await visibleRect(page.locator('action-menu').locator('.btn--menu'), 420, 'editing navigation');
      const editor = await content.boundingBox();
      assert(nav.y + nav.height <= editor.y, 'Navigation must not cover the editor');
      const done = await visibleRect(page.getByRole('button', { name: '完了', exact: true }), 420, 'Done');
      list.keyboardDone = done;
      await screenshot(page, profile, 'compose-keyboard');
    }
    await click(page.getByRole('button', { name: '完了', exact: true }));
    await page.waitForFunction(() => !document.querySelector('.memo-compose-mobile-modal.is-open') && !document.querySelector('#memo-composer.is-expanded'));
    assert.equal(postCount(), before + 1);
    if (mobile) await iosViewport(page, height);
    await click(page.getByRole('button', { name: 'チェックリストを作成', exact: true }));
    await content.waitFor({ state: 'visible' });
    assert.equal(await content.inputValue(), '- [ ] ');
    assert(await page.getByRole('button', { name: '完了', exact: true }).isDisabled(), 'Empty checklist must not be submitted');
    assert.equal(postCount(), before + 1, 'Checklist marker must not be saved before typing');
    await content.fill('- [ ] 牛乳を買う');
    await click(page.getByRole('button', { name: '完了', exact: true }));
    await page.waitForTimeout(200);
    assert.equal(postCount(), before + 2);
    await click(page.locator('.memo-quick-capture__collapsed').getByRole('button', { name: '色を選択', exact: true }));
    await click(page.getByRole('option', { name: 'ミント', exact: true }));
    await content.fill('色付きのメモを確認します。');
    await click(page.getByRole('button', { name: '完了', exact: true }));
    await page.waitForTimeout(200);
    assert.equal(postCount(), before + 3);
    assert.equal(fixture.memos[0].background_color, '#dcfce7');

    await click(page.locator('.memo-item').filter({ hasText: '週末の買い物と家事のメモ' }).locator('.memo-item__open'));
    const detail = page.locator('#memo-detail-modal.is-open');
    await detail.waitFor();
    await visibleRect(detail.getByRole('button', { name: '全文をコピー', exact: true }), height, 'Copy');
    const more = detail.locator('summary');
    await click(more);
    await click(detail.getByRole('option', { name: 'ブルー', exact: true }));
    await click(detail.getByRole('button', { name: 'コレクション', exact: true }));
    await click(page.getByRole('option', { name: longCollection, exact: true }));
    await iconTargets(page);
    await more.press('Escape');
    assert(await detail.isVisible(), 'Closing organize controls must keep the detail open');
    await screenshot(page, profile, 'detail');
    await click(detail.getByRole('tab', { name: '編集', exact: true }));
    await detail.getByRole('textbox', { name: '内容', exact: true }).fill(`${longBody}\n\n追記した本文`);
    await page.waitForTimeout(1000);
    assert(fixture.writes.some(w => w.method === 'PATCH' && w.input.ai_response?.includes('追記した本文')));
    const ai = mobile ? detail.getByRole('tab', { name: 'このメモについてAIに質問・編集', exact: true }) : detail.getByRole('button', { name: 'このメモについてAIに質問・編集', exact: true });
    await click(ai);
    const input = detail.getByRole('textbox', { name: 'AIサポートへのメッセージ', exact: true });
    await input.fill('このメモの確認をお願いします。');
    if (mobile) {
      await iosViewport(page, 420);
      list.keyboardAi = await visibleRect(input, 420, 'AI input');
      await visibleRect(detail.getByRole('button', { name: 'メッセージを送信', exact: true }), 420, 'AI send');
      await screenshot(page, profile, 'agent-keyboard');
      await click(detail.getByRole('tab', { name: 'プレビュー', exact: true }));
      assert(!(await input.isVisible()));
      await click(ai);
      assert.equal(await input.inputValue(), 'このメモの確認をお願いします。');
    }
    await click(detail.getByRole('button', { name: 'メッセージを送信', exact: true }));
    await detail.getByText('検証用の応答です。', { exact: true }).waitFor();
    assert(fixture.writes.some(w => w.endpoint === '/api/ai-agent'));
    await click(detail.getByRole('button', { name: '閉じる', exact: true }));
    await page.waitForTimeout(300);
    if (mobile) await iosViewport(page, height);

    if (width <= 1024) {
      await click(page.getByRole('button', { name: '表示・整理メニュー', exact: true }));
      for (const name of ['すべてのメモ', 'アーカイブ', 'ゴミ箱', 'コレクションを管理']) assert(await page.getByRole('button', { name, exact: true }).last().isVisible(), `${profile}: ${name} unreachable`);
      await screenshot(page, profile, 'organize');
      await click(page.getByRole('button', { name: 'コレクションを管理', exact: true }).last());
    } else {
      const collection = page.locator('.memo-sidebar-collection-item').filter({ hasText: longCollection });
      await page.getByRole('button', { name: 'サイドバーを折りたたむ', exact: true }).click();
      await iconTargets(page);
      const expand = page.getByRole('button', { name: 'サイドバーを展開', exact: true });
      const rect = await expand.boundingBox();
      assert(rect && rect.width >= 44 && rect.height >= 44);
      await expand.click();
      await collection.hover();
      await page.getByRole('tooltip').getByText(longCollection, { exact: true }).waitFor();
      await collection.focus();
      await screenshot(page, profile, 'collection-tooltip');
      await click(page.getByRole('button', { name: 'コレクションを管理', exact: true }).first());
    }
    const modal = page.locator('#memo-collection-modal.is-open');
    const name = modal.getByRole('textbox', { name: '新しいコレクション名', exact: true });
    await name.fill('検証用コレクション');
    if (mobile) {
      await iosViewport(page, 420);
      await visibleRect(name, 420, 'collection name');
      list.keyboardCollectionCreate = await visibleRect(modal.getByRole('button', { name: '作成', exact: true }), 420, 'collection create');
      await screenshot(page, profile, 'collection-keyboard');
      await iosViewport(page, 300);
      await visibleRect(modal.getByRole('button', { name: '作成', exact: true }), 300, 'short viewport collection create');
    }
    await click(modal.getByRole('button', { name: '作成', exact: true }));
    await page.waitForTimeout(200);
    assert(fixture.collections.some(c => c.name === '検証用コレクション'));
    await iconTargets(page);
    if (width === 390 && theme === 'light') {
      await click(modal.getByRole('button', { name: '閉じる', exact: true }));
      await page.waitForTimeout(250);
      await page.evaluate(() => { delete window.visualViewport.height; });
      await page.setViewportSize({ width: 390, height: 420 });
      await click(page.getByRole('button', { name: 'テキストメモを作成', exact: true }));
      await content.fill(longBody);
      await page.waitForTimeout(200);
      await visibleRect(content, 420, 'Android editor');
      list.androidDone = await visibleRect(page.getByRole('button', { name: '完了', exact: true }), 420, 'Android Done');
      await screenshot(page, profile, 'android-keyboard');
      await page.evaluate(() => {
        Object.defineProperty(window.visualViewport, 'height', { configurable: true, get: () => 300 });
        Object.defineProperty(window.visualViewport, 'offsetTop', { configurable: true, get: () => 80 });
        window.visualViewport.dispatchEvent(new Event('resize'));
        window.visualViewport.dispatchEvent(new Event('scroll'));
      });
      await page.waitForTimeout(200);
      await visibleRect(content, 300, 'panned editor', 80);
      list.pannedDone = await visibleRect(page.getByRole('button', { name: '完了', exact: true }), 300, 'panned Done', 80);
      await page.evaluate(() => { delete window.visualViewport.height; delete window.visualViewport.offsetTop; });
      await page.setViewportSize({ width: 740, height: 390 });
      await page.waitForTimeout(250);
      await visibleRect(content, 390, 'landscape editor');
      await visibleRect(page.getByRole('button', { name: '完了', exact: true }), 390, 'landscape Done');
      await screenshot(page, profile, 'landscape');
    }
    assert.deepEqual(errors, [], `${profile}: browser errors`);
    results.push({ profile, width, height, theme, list, writes: fixture.writes.length, errors });
    await writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
    process.stdout.write(`${JSON.stringify({ profile, status: 'passed', writes: fixture.writes.length })}\n`);
    await context.close();
  }
} finally {
  await browser.close();
}
