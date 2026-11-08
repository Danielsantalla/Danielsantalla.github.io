/* Same-origin cache only. No X widgets, third-party requests or credentials. */
(async () => {
  const slots = [...document.querySelectorAll('[data-tweet-metrics]')];
  if (!slots.length) return;
  try {
    const response = await fetch('/data/tweet-metrics.json', {cache:'no-cache'});
    if (!response.ok) return;
    const cache = await response.json();
    if (cache.schema_version !== 1) return;
    const icons = ['♡','↩','⇄'];
    const fields = ['like_count','reply_count','retweet_count'];
    const labels = ['likes','replies','reposts'];
    slots.forEach(slot => {
      const p = cache.posts?.[slot.dataset.tweetMetrics];
      const date = p && new Date(p.updated_at);
      if (!p || !Number.isFinite(date.getTime()) || date > new Date() || Date.now()-date > 14*86400000 || !fields.every(k=>Number.isSafeInteger(p[k]) && p[k]>=0)) return;
      fields.forEach((key,i) => {
        const span = document.createElement('span');
        span.textContent = `${icons[i]} ${p[key].toLocaleString('en-US')}`;
        span.setAttribute('aria-label', `${p[key]} ${labels[i]}`);
        span.title = `${p[key].toLocaleString('en-US')} ${labels[i]}`;
        slot.append(span);
      });
      const time = document.createElement('time');
      time.dateTime=p.updated_at;
      time.textContent='Updated '+date.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
      slot.append(time); slot.hidden=false;
    });
  } catch { /* Keep tutorials usable when metrics are unavailable. */ }
})();
