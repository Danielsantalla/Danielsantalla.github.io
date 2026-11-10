/* Public, same-origin API snapshots. No social widgets or embedded posts. */
(async () => {
  'use strict';
  const slots = [...document.querySelectorAll('[data-tweet-metrics]')];
  if (!slots.length) return;
  const MAX_AGE = 14 * 86400000;
  const xId = value => typeof value === 'string' && /^\d{1,25}$/.test(value);
  const ytId = value => typeof value === 'string' && /^[A-Za-z0-9_-]{11}$/.test(value);
  const commentId = value => typeof value === 'string' && /^[A-Za-z0-9_.-]{1,200}$/.test(value);
  const source = (platform, id) => platform === 'x' ? `https://x.com/i/status/${id}` : `https://www.youtube.com/watch?v=${id}`;
  const element = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const link = (url, text) => {
    const node = element('a', 'conversation-source', text);
    node.href = url; node.target = '_blank'; node.rel = 'noopener noreferrer';
    return node;
  };
  function youtubeLegalLinks() {
    const notice = element('p', 'social-legal');
    notice.append(link('/privacy/', 'Privacy'), link('https://www.youtube.com/t/terms', 'YouTube terms'));
    return notice;
  }
  // Keep disclosure links outside tutorial links and away from the statistics.
  const listing = slots.map(slot => slot.closest('.lesson-list')).find(Boolean);
  if (listing && slots.some(slot => ytId(slot.dataset.youtubeId))) {
    const notice = youtubeLegalLinks();
    notice.append(element('span', 'metrics-legend', 'The eye combines YouTube views and X impressions, not unique viewers. A trailing + means some counts are unavailable.'));
    listing.after(notice);
  }
  const safeURL = (value, hosts, path) => {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password && !url.port && hosts.includes(url.hostname) && (!path || path.test(url.pathname)) ? url.href : null;
    } catch { return null; }
  };
  const fresh = (entry, platform) => {
    const date = typeof entry?.updated_at === 'string' ? Date.parse(entry.updated_at) : NaN;
    return Number.isFinite(date) && date <= Date.now() && (platform === 'x' && entry.mode === 'one_time' || Date.now() - date < MAX_AGE);
  };
  const fields = {
    x: [['like_count','likes'],['reply_count','replies'],['retweet_count','reposts'],['quote_count','quotes'],['impression_count','impressions']],
    youtube: [['view_count','views'],['like_count','likes'],['comment_count','comments']]
  };
  const metrics = (entry, platform) => fields[platform].filter(([key]) => Number.isSafeInteger(entry?.metrics?.[key]) && entry.metrics[key] >= 0 &&
    // Guard old cached snapshots too: these legacy API zeros are not verified.
    !(platform === 'x' && key === 'impression_count' && entry.metrics[key] === 0 && entry.impressions_status !== 'owner_verified'));
  const listMetrics = [
    {kind:'views', keys:{x:'impression_count',youtube:'view_count'}, names:{x:'X post impressions',youtube:'YouTube video views'}, path:'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z'},
    {kind:'likes', keys:{x:'like_count',youtube:'like_count'}, names:{x:'X likes',youtube:'YouTube likes'}, path:'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z'},
    {kind:'comments', keys:{x:'reply_count',youtube:'comment_count'}, names:{x:'X replies',youtube:'YouTube comments'}, path:'M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z'}
  ];
  function metricIcon(path) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('class','metric-icon'); svg.setAttribute('viewBox','0 0 24 24');
    svg.setAttribute('width','14'); svg.setAttribute('height','14');
    svg.setAttribute('aria-hidden','true'); svg.setAttribute('focusable','false');
    const shape = document.createElementNS('http://www.w3.org/2000/svg','path'); shape.setAttribute('d',path);
    svg.append(shape); return svg;
  }
  const dateLabel = value => new Date(value).toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric', timeZone:'UTC'});
  const impressionsNote = entry => {
    const evidence = entry?.impressions_source;
    return entry?.impressions_status === 'owner_verified' && evidence?.source_kind === 'owner_analytics_screenshot' &&
      /^\d{4}-\d{2}-\d{2}$/.test(evidence.verified_on || '') && Number.isFinite(Date.parse(evidence.verified_on))
      ? `Impressions from the owner's X Analytics screenshot, verified ${dateLabel(evidence.verified_on)}. Not live.` : '';
  };
  const validX = c => c && xId(c.id) && xId(c.author_id) &&
    typeof c.author === 'string' && c.author.trim() && typeof c.text === 'string' && c.text.trim() &&
    typeof c.username === 'string' && /^[A-Za-z0-9_]{1,15}$/.test(c.username) &&
    safeURL(c.author_image_url, ['pbs.twimg.com', 'abs.twimg.com']) &&
    safeURL(c.author_url, ['x.com'], new RegExp(`^/${c.username}/?$`, 'i')) &&
    typeof c.published_at === 'string' && Number.isFinite(Date.parse(c.published_at));
  function xText(comment) {
    const p = element('p', 'x-comment-text'), text = comment.text, spans = [];
    // X entity indices can refer to Unicode code points. Accept UTF-16 offsets
    // only when the exact entity text agrees; never splice an unverified range.
    const points = Array.from(text), offsets = [0];
    points.forEach(point => offsets.push(offsets[offsets.length - 1] + point.length));
    const entities = comment.entities || {};
    for (const kind of ['urls', 'mentions', 'hashtags', 'cashtags']) {
      for (const entity of Array.isArray(entities[kind]) ? entities[kind] : []) {
        if (!entity || typeof entity !== 'object') continue;
        let token, href;
        if (kind === 'urls') {
          token = entity.url;
          try {
            const url = new URL(entity.url);
            if (url.protocol === 'https:' && !url.username && !url.password) href = url.href;
          } catch { /* Keep unsafe links as plain text. */ }
        } else if (kind === 'mentions' && /^[A-Za-z0-9_]{1,15}$/.test(entity.username || '')) {
          token = '@' + entity.username; href = 'https://x.com/' + entity.username;
        } else if ((kind === 'hashtags' || kind === 'cashtags') && typeof entity.tag === 'string' && /^[\p{L}\p{N}_]+$/u.test(entity.tag)) {
          token = (kind === 'hashtags' ? '#' : '$') + entity.tag;
          href = kind === 'hashtags' ? 'https://x.com/hashtag/' + encodeURIComponent(entity.tag) : 'https://x.com/search?q=' + encodeURIComponent(token);
        }
        if (!href || typeof token !== 'string' || !token) continue;
        const start = entity.start, end = entity.end;
        let range;
        if (Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start) {
          for (const [a,b] of [[offsets[start],offsets[end]],[start,end]]) {
            if (Number.isInteger(a) && Number.isInteger(b) && text.slice(a,b) === token) { range = [a,b]; break; }
          }
        }
        // Without reliable indices link only an unambiguous exact occurrence.
        if (!range) {
          const a = text.indexOf(token);
          if (a >= 0 && text.indexOf(token, a + 1) < 0) range = [a,a + token.length];
        }
        if (range) spans.push({start:range[0],end:range[1],href,label:kind === 'urls' && typeof entity.display_url === 'string' ? entity.display_url : undefined});
      }
    }
    let cursor = 0;
    for (const span of spans.sort((a,b) => a.start - b.start)) {
      if (span.start < cursor) continue;
      p.append(document.createTextNode(text.slice(cursor,span.start)),link(span.href,span.label || text.slice(span.start,span.end)));
      cursor = span.end;
    }
    p.append(document.createTextNode(text.slice(cursor)));
    return p;
  }
  function xComment(comment) {
    const article = element('article', 'sample-comment x-comment');
    const avatarLink = link(comment.author_url, '');
    const avatar = element('img', 'sample-avatar');
    avatar.src = safeURL(comment.author_image_url, ['pbs.twimg.com', 'abs.twimg.com']);
    avatar.alt = ''; avatar.loading = 'lazy'; avatar.referrerPolicy = 'no-referrer';
    avatarLink.setAttribute('aria-label', comment.author + ' on X'); avatarLink.append(avatar);
    const body = element('div'), byline = element('div', 'sample-byline');
    const author = link(comment.author_url, '');
    author.append(element('strong', '', comment.author),element('span', 'x-username', '@' + comment.username));
    byline.append(author);
    const footer = element('div', 'x-comment-meta');
    const postURL = source('x', comment.id);
    const dated = link(postURL, ''), time = element('time', '', dateLabel(comment.published_at));
    time.dateTime = comment.published_at; dated.append(time);
    footer.append(dated,link(postURL,'View on X ↗'));
    if (Array.isArray(comment.edit_history_tweet_ids) && comment.edit_history_tweet_ids.filter(xId).length > 1) footer.append(link(postURL, 'Edited'));  
    body.append(byline,xText(comment),footer); article.append(avatarLink,body);
    return article;
  }
  let cache = {schema_version:1, x:{}, youtube:{}};
  const controller = new AbortController();
  const fetchTimer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch('/data/social.json', {cache:'no-cache', credentials:'omit', signal:controller.signal});
    if (response.ok) {
      const data = await response.json();
      if (data.schema_version === 1) cache = data;
    }
  } catch { /* Source links remain useful when the cache is unavailable. */ }
  finally { clearTimeout(fetchTimer); }
  slots.forEach((slot, index) => {
    const ids = {x: xId(slot.dataset.tweetMetrics) ? slot.dataset.tweetMetrics : null, youtube: ytId(slot.dataset.youtubeId) ? slot.dataset.youtubeId : null};
    const platforms = ['x','youtube'].filter(platform => ids[platform]);
    const get = platform => {
      const entry = ids[platform] && cache[platform]?.[ids[platform]];
      return fresh(entry, platform) ? entry : null;
    };
    const isList = !!slot.closest('.lesson-list');
    let selectedPlatform;
    function render() {
      slot.replaceChildren();
      if (isList) {
        slot.className = 'combined-metrics';
        slot.removeAttribute('aria-label');
        for (const metric of listMetrics) {
          const values = platforms.map(platform => {
            const entry = get(platform), key = metric.keys[platform];
            const available = metrics(entry, platform).some(([field]) => field === key);
            return {platform,entry,value:available ? entry.metrics[key] : null};
          });
          const available = values.filter(item => item.value !== null);
          if (!available.length) continue;
          const total = available.reduce((sum,item) => sum + item.value,0);
          if (!Number.isSafeInteger(total)) continue;
          const partial = available.length < values.length, formatted = total.toLocaleString('en-US');
          const name = metric.kind === 'views' ? platforms.map(p => metric.names[p]).join(' and ') : metric.kind === 'comments' ? 'comments and replies' : 'likes';
          const details = values.map(({platform,entry,value}) => {
            if (value === null) return `${metric.names[platform]} unavailable`;
            let detail = `${metric.names[platform]}: ${value.toLocaleString('en-US')}. `;
            detail += platform === 'x' ? `Snapshot from ${dateLabel(entry.updated_at)} (UTC), not live` : `Updated ${dateLabel(entry.updated_at)} (UTC)`;
            if (platform === 'x' && metric.kind === 'views' && impressionsNote(entry)) detail += '. ' + impressionsNote(entry);
            return detail;
          }).join('. ');
          const label = `${partial ? 'At least ' : ''}${formatted} ${name}. ${metric.kind === 'views' ? 'Different platform measures, not unique viewers. ' : ''}${details}${partial ? '. + indicates an unavailable contribution, not zero.' : ''}`;
          const item = element('span','summary-metric summary-metric-' + metric.kind);
          item.setAttribute('role','img'); item.setAttribute('aria-label',label); item.title = label;
          const count = element('span','metric-count',formatted + (partial ? '+' : ''));
          count.setAttribute('aria-hidden','true');
          item.append(metricIcon(metric.path),count); slot.append(item);
        }
        slot.hidden = !slot.childNodes.length;
        return;
      }
      slot.className = 'sample-comments platform-conversation'; slot.hidden = false;
      slot.setAttribute('aria-label', 'Social discussion');
      if (!platforms.length) {
        slot.append(element('p','sample-note','No social sources linked for this tutorial.'));
        return;
      }
      const tabs = element('div','platform-tabs'); tabs.setAttribute('role','tablist'); tabs.setAttribute('aria-label','Discussion platform');
      const panels = [], buttons = [];
      for (const platform of platforms) {
        const label = platform === 'x' ? 'X' : 'YouTube';
        const button = element('button','',label); button.type = 'button'; button.setAttribute('role','tab');
        if (platform === 'x') {
          button.textContent = ''; button.setAttribute('aria-label', 'X');
          const logo = element('img', 'x-tab-logo'); logo.src = '/assets/x-logo.svg'; logo.alt = 'X'; logo.width = 14; logo.height = 14;
          button.append(logo);
        }
        const panel = element('div','platform-panel'); panel.setAttribute('role','tabpanel'); panel.tabIndex = 0;
        button.id = `social-${index}-${platform}-tab`; panel.id = `social-${index}-${platform}-panel`;
        button.setAttribute('aria-controls',panel.id); panel.setAttribute('aria-labelledby',button.id);
        tabs.append(button); buttons.push(button); panels.push(panel);
        const entry = get(platform), available = metrics(entry, platform);
        if (available.length) {
          const stats = element('div','platform-metrics');
          for (const [key,name] of available) {
            const item = element('div'); item.append(element('strong','',entry.metrics[key].toLocaleString('en-US')),element('span','',name)); stats.append(item);
          }
          panel.append(stats);
        }
        if (entry) {
          const updated = element('time','sample-note',platform === 'x' ? `Snapshot from ${dateLabel(entry.updated_at)} (UTC), not live` : `Updated ${dateLabel(entry.updated_at)} (UTC) · refreshed weekly`); updated.dateTime = entry.updated_at; panel.append(updated);
          if (platform === 'x' && impressionsNote(entry)) panel.append(element('p','sample-note',impressionsNote(entry)));
        }
        if (!ids[platform]) panel.append(element('p','sample-note',`No ${label} source linked for this tutorial.`));
        else if (!entry) panel.append(element('p','sample-note',`${label} statistics and comments are currently unavailable.`));
        if (entry) {
          const comments = Array.isArray(entry.comments) ? entry.comments : [];
          const valid = comments.filter(c => c && (platform === 'x' ? validX(c) : commentId(c.id) && typeof c.text === 'string' && typeof c.author === 'string'));
          if (valid.length) {
            panel.append(element('p','sample-note',platform === 'x' ? 'Replies from the original conversation on X.' : 'Recent comments from YouTube. Comments belong to their authors.'));
            let more;
            valid.forEach((comment, n) => {
              if (n === 3) { more = element('details'); more.append(element('summary','','More comments')); panel.append(more); }
              const target = n < 3 ? panel : more;
              if (platform === 'youtube') {
                const article = element('article','sample-comment');
                // Initials keep comments readable without requests to Google image servers.
                const avatar = element('span', 'sample-avatar', comment.author.slice(0,1));
                avatar.setAttribute('aria-hidden', 'true');
                const body = element('div'), byline = element('div','sample-byline');
                const authorURL = safeURL(comment.author_channel_url,['www.youtube.com','youtube.com'],/^\/(channel\/UC[A-Za-z0-9_-]+|@[A-Za-z0-9_.%-]+)\/?$/);
                const author = element('strong','',comment.author);
                if (authorURL) { const authorLink = link(authorURL,''); authorLink.append(author); byline.append(authorLink); } else byline.append(author);
                if (typeof comment.published_at === 'string' && Number.isFinite(Date.parse(comment.published_at))) {
                  const time = element('time','',dateLabel(comment.published_at)); time.dateTime = comment.published_at; byline.append(time);
                }
                body.append(byline,element('p','',comment.text),link(`${source(platform,ids[platform])}&lc=${encodeURIComponent(comment.id)}`,'View on YouTube ↗'));
                article.append(avatar,body); target.append(article);
              } else {
                target.append(xComment(comment));
              }
            });
          } else panel.append(element('p','sample-note',entry.comments_status === 'disabled' ? 'Comments are disabled on this video.' : 'No comments are available in this snapshot.'));
        }
        if (ids[platform]) panel.append(link(source(platform,ids[platform]),`Join the conversation on ${label} ↗`));
        if (platform === 'youtube') panel.append(youtubeLegalLinks());
      }
      function select(n, focus = false) {
        selectedPlatform = platforms[n];
        buttons.forEach((button,i) => { button.setAttribute('aria-selected',String(i === n)); button.tabIndex = i === n ? 0 : -1; panels[i].hidden = i !== n; });
        if (focus) buttons[n].focus();
      }
      buttons.forEach((button,n) => {
        button.addEventListener('click',() => select(n));
        button.addEventListener('keydown',event => {
          let next;
          if (event.key === 'ArrowRight') next = (n + 1) % buttons.length;
          if (event.key === 'ArrowLeft') next = (n + buttons.length - 1) % buttons.length;
          if (event.key === 'Home') next = 0;
          if (event.key === 'End') next = buttons.length - 1;
          if (next !== undefined) { event.preventDefault(); select(next,true); }
        });
      });
      slot.append(tabs,...panels);
      // Prefer a platform with fresh data.
      const firstFresh = platforms.findIndex(platform => fresh(cache[platform]?.[ids[platform]], platform));
      const previous = platforms.indexOf(selectedPlatform);
      const fallback = Math.max(0, platforms.indexOf('youtube'));
      select(previous >= 0 ? previous : (firstFresh < 0 ? fallback : firstFresh));
    }
    render();
    // Remove a snapshot if it becomes stale while this page remains open.
    const expiries = platforms.filter(p => !(p === 'x' && cache[p]?.[ids[p]]?.mode === 'one_time')).map(p => cache[p]?.[ids[p]]).filter(e => fresh(e)).map(e => Date.parse(e.updated_at)+MAX_AGE-Date.now()+1);
    expiries.forEach(delay => setTimeout(render,Math.max(1,delay)));
  });
})();
