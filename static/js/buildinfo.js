// Shows at the top of the page which code is running: commit, its time and when the app started.
(function () {
  const box = document.getElementById('buildinfo');
  if (!box) return;
  const fmt = iso => new Date(iso).toLocaleString('de-DE', {dateStyle: 'short', timeStyle: 'short'});
  fetch('/api/version').then(r => r.json()).then(r => {
    const d = r.data || {};
    const t = d.build_time && d.build_time !== 'unknown' ? fmt(d.build_time) : '?';
    box.textContent = `Stand ${d.build_sha || '?'} · ${t}`;
    box.title = `Code-Stand (Commit) ${d.build_sha || '?'}\n` +
      (d.build_time_kind === 'commit' ? 'Zeit des Commits' : d.build_time_kind === 'build' ? 'Zeit des Builds' : 'Zeit unbekannt') + `: ${t}\n` +
      (d.started ? `App gestartet: ${fmt(d.started)}` : '') + `\nModus: ${d.app_mode || '?'}`;
  }).catch(() => { box.textContent = 'Stand ?'; });
})();
