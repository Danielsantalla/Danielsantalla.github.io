/* Public, same-origin API cache. X embeds are loaded only after explicit consent. */
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
  let youtubeConsent = false;
  const renderers = [];
  function youtubeConsentPrompt() {
    const prompt = element('div', 'youtube-consent');
    prompt.append(element('p', 'sample-note', 'YouTube statistics, comments and author images are optional. Images may contact Google and share your IP address.'));
    const terms = element('p', 'sample-note', 'By selecting “Agree and show YouTube”, you agree to this site’s privacy policy and to be bound by the YouTube Terms of Service.');
    terms.append(link('/privacy/', 'Privacy and YouTube terms'), link('https://www.youtube.com/t/terms', 'YouTube Terms of Service'));
    const button = element('button', 'load-embed', 'Agree and show YouTube'); button.type = 'button';
    button.addEventListener('click', () => {
      if (youtubeConsent) return;
      youtubeConsent = true;
      prompt.hidden = true;
      renderers.forEach(render => render(true));
    });
    prompt.append(terms, button);
    return prompt;
  }
  // Consent controls stay outside tutorial links to avoid nested interactive elements.
  const listing = slots.map(slot => slot.closest('.lesson-list')).find(Boolean);
  if (listing && slots.some(slot => ytId(slot.dataset.youtubeId))) listing.before(youtubeConsentPrompt());
  const safeURL = (value, hosts, path) => {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password && !url.port && hosts.includes(url.hostname) && (!path || path.test(url.pathname)) ? url.href : null;
    } catch { return null; }
  };
  const fresh = entry => {
    const date = typeof entry?.updated_at === 'string' ? Date.parse(entry.updated_at) : NaN;
    return Number.isFinite(date) && date <= Date.now() && Date.now() - date <= MAX_AGE;
  };
  const fields = {
    x: [['like_count','likes'],['reply_count','replies'],['retweet_count','reposts'],['quote_count','quotes'],['impression_count','views']],
    youtube: [['view_count','views'],['like_count','likes'],['comment_count','comments']]
  };
  const metrics = (entry, platform) => fields[platform].filter(([key]) => Number.isSafeInteger(entry?.metrics?.[key]) && entry.metrics[key] >= 0);
  const dateLabel = value => new Date(value).toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric', timeZone:'UTC'});
  let widgetPromise;
  function loadWidgets() {
    if (widgetPromise) return widgetPromise;
    widgetPromise = new Promise((resolve, reject) => {
      if (window.twttr?.widgets?.createTweet) return resolve(window.twttr.widgets);
      const script = element('script');
      const timer = setTimeout(() => reject(new Error('X unavailable')), 15000);
      script.src = 'https://platform.twitter.com/widgets.js'; script.async = true;
      script.onload = () => { clearTimeout(timer); window.twttr?.widgets?.createTweet ? resolve(window.twttr.widgets) : reject(new Error('X unavailable')); };
      script.onerror = () => { clearTimeout(timer); reject(new Error('X unavailable')); };
      document.head.append(script);
    });
    return widgetPromise;
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
      if (platform === 'youtube' && !youtubeConsent) return null;
      const entry = ids[platform] && cache[platform]?.[ids[platform]];
      return fresh(entry) ? entry : null;
    };
    const isList = !!slot.closest('.lesson-list');
    let selectedPlatform;
    function render(focus = false) {
      slot.replaceChildren();
      if (isList) {
        slot.className = 'combined-metrics';
        for (const platform of platforms) {
          const entry = get(platform), available = metrics(entry, platform);
          if (!available.length) continue;
          const row = element('span', 'platform-stat-line');
          row.append(element('strong', '', platform === 'x' ? 'X' : 'YouTube'));
          for (const [key,label] of available) row.append(element('span','',`${entry.metrics[key].toLocaleString('en-US')} ${label}`));
          row.title = `Updated ${dateLabel(entry.updated_at)} (UTC)`;
          slot.append(row);
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
        const panel = element('div','platform-panel'); panel.setAttribute('role','tabpanel'); panel.tabIndex = 0;
        button.id = `social-${index}-${platform}-tab`; panel.id = `social-${index}-${platform}-panel`;
        button.setAttribute('aria-controls',panel.id); panel.setAttribute('aria-labelledby',button.id);
        tabs.append(button); buttons.push(button); panels.push(panel);
        if (platform === 'youtube' && !youtubeConsent) {
          panel.append(youtubeConsentPrompt(), link(source(platform, ids[platform]), 'Visit YouTube without loading data here ↗'));
          continue;
        }
        const entry = get(platform), available = metrics(entry, platform);
        if (available.length) {
          const stats = element('div','platform-metrics');
          for (const [key,name] of available) {
            const item = element('div'); item.append(element('strong','',entry.metrics[key].toLocaleString('en-US')),element('span','',name)); stats.append(item);
          }
          panel.append(stats);
        }
        if (entry) {
          const updated = element('time','sample-note',`Updated ${dateLabel(entry.updated_at)} (UTC) · refreshed weekly`); updated.dateTime = entry.updated_at; panel.append(updated);
        }
        if (!ids[platform]) panel.append(element('p','sample-note',`No ${label} source linked for this tutorial.`));
        else if (!entry) panel.append(element('p','sample-note',`${label} statistics and comments are currently unavailable.`));
        if (entry) {
          const comments = Array.isArray(entry.comments) ? entry.comments : [];
          const valid = comments.filter(c => c && (platform === 'x' ? xId(c.id) : commentId(c.id) && typeof c.text === 'string' && typeof c.author === 'string'));
          if (valid.length) {
            panel.append(element('p','sample-note',platform === 'x' ? 'Replies from the original conversation on X.' : 'Recent comments from YouTube. Comments belong to their authors.'));
            let more;
            valid.forEach((comment, n) => {
              if (n === 3) { more = element('details'); more.append(element('summary','','More comments')); panel.append(more); }
              const target = n < 3 ? panel : more;
              if (platform === 'youtube') {
                const article = element('article','sample-comment');
                const avatarURL = safeURL(comment.author_image_url,['yt3.ggpht.com','yt3.googleusercontent.com','lh3.googleusercontent.com']);
                const avatar = element(avatarURL ? 'img' : 'span','sample-avatar',avatarURL ? undefined : comment.author.slice(0,1));
                if (avatarURL) { avatar.src = avatarURL; avatar.alt = ''; avatar.width = 24; avatar.height = 24; avatar.loading = 'lazy'; avatar.referrerPolicy = 'no-referrer'; }
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
                const article = element('div','x-reply'); article.dataset.postId = comment.id;
                article.append(link(source('x',comment.id),'View reply on X ↗')); target.append(article);
              }
            });
            if (platform === 'x') {
              const consent = element('p','sample-note','Loading replies contacts X and allows its embedded content to use cookies and receive your IP address.');
              const load = element('button','load-embed','Load X replies'); load.type = 'button';
              load.addEventListener('click', async () => {
                if (load.disabled) return;
                load.disabled = true; load.textContent = 'Loading X replies…';
                try {
                  const widgets = await loadWidgets();
                  if (!fresh(entry) || !panel.isConnected) return;
                  const loaded = await Promise.all([...panel.querySelectorAll('.x-reply')].map(async reply => {
                    const embed = element('div','x-embed'); reply.append(embed);
                    try { return !!await widgets.createTweet(reply.dataset.postId,embed,{dnt:true,conversation:'none',align:'left'}); } catch { return false; }
                  }));
                  load.textContent = loaded.every(Boolean) ? 'X replies loaded.' : 'Some replies could not load. Use the source links below.';
                } catch { load.textContent = 'X replies could not load. Use the source links below.'; }
              });
              panel.insertBefore(consent,panel.querySelector('.x-reply')); panel.insertBefore(load,panel.querySelector('.x-reply'));
            }
          } else panel.append(element('p','sample-note',entry.comments_status === 'disabled' ? 'Comments are disabled on this video.' : 'No comments are available in this snapshot.'));
        }
        if (ids[platform]) panel.append(link(source(platform,ids[platform]),`Join the conversation on ${label} ↗`));
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
      const firstFresh = platforms.findIndex(platform => get(platform));
      const previous = platforms.indexOf(selectedPlatform);
      select(previous >= 0 ? previous : (firstFresh < 0 ? 0 : firstFresh), focus && selectedPlatform === 'youtube');
    }
    renderers.push(render);
    render();
    // Remove a snapshot if it becomes stale while this page remains open.
    const expiries = platforms.map(p => cache[p]?.[ids[p]]).filter(e => fresh(e)).map(e => Date.parse(e.updated_at)+MAX_AGE-Date.now()+1);
    expiries.forEach(delay => setTimeout(render,Math.max(1,delay)));
  });
})();
