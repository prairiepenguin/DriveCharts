const ERA_COLORS = {
  ttu: "#CC0000",
  uiw: "#C41E3A",
  wsu: "#981E32",
  unt: "#00853E",
  osu: "#FF7300",
};

const BUCKETS = ["1-2", "3", "4-6", "7-9", "10", "11-15", "16+"];

const state = {
  era: "",
  season: "",
  excludeGarbage: true,
  tab: "playbook",
  selectedGame: null,
  cell: null,
  meta: null,
};

const $ = (id) => document.getElementById(id);

function pct(v) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

function num(v, d = 1) {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toFixed(d);
}

function qs() {
  const p = new URLSearchParams();
  if (state.era) p.set("era", state.era);
  if (state.season) p.set("season", state.season);
  p.set("exclude_garbage", state.excludeGarbage ? "true" : "false");
  return p.toString();
}

async function get(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

function mixColor(passRate) {
  if (passRate == null) return "#1a241c";
  const run = [47, 158, 95];
  const pass = [255, 106, 18];
  const t = Math.min(1, Math.max(0, (passRate - 0.35) / 0.4));
  const rgb = run.map((c, i) => Math.round(c + (pass[i] - c) * t));
  return `rgb(${rgb.join(",")})`;
}

function resultColor(result) {
  if (result === "TD") return "var(--td)";
  if (result === "FG") return "var(--fg)";
  if (result === "INT" || result === "FUMBLE") return "var(--to)";
  if (result === "DOWNS") return "var(--downs)";
  return "var(--punt)";
}

async function boot() {
  const health = await get("/api/health");
  if (!health.ok) {
    $("main").innerHTML = `<div class="panel">${health.error || "Dataset missing. Run python -m pipeline.ingest"}</div>`;
    return;
  }
  state.meta = await get("/api/meta");
  renderFilters();
  await refresh();
}

function renderFilters() {
  const eras = $("eras");
  eras.innerHTML = "";
  const all = document.createElement("button");
  all.className = `era ${state.era ? "" : "on"}`;
  all.innerHTML = `<span class="dot" style="background:#fff"></span>All eras`;
  all.onclick = () => {
    state.era = "";
    state.cell = null;
    refresh();
  };
  eras.appendChild(all);
  for (const era of state.meta.eras) {
    const btn = document.createElement("button");
    btn.className = `era ${state.era === era.era_id ? "on" : ""}`;
    btn.innerHTML = `<span class="dot" style="background:${ERA_COLORS[era.era_id] || "#fff"}"></span>${era.era} <span style="color:var(--muted)">${era.role}</span>`;
    btn.onclick = () => {
      state.era = era.era_id;
      state.cell = null;
      refresh();
    };
    eras.appendChild(btn);
  }

  const season = $("season");
  const keep = state.season;
  season.innerHTML = `<option value="">All seasons</option>`;
  for (const yr of state.meta.seasons) {
    const opt = document.createElement("option");
    opt.value = yr;
    opt.textContent = yr;
    if (String(keep) === String(yr)) opt.selected = true;
    season.appendChild(opt);
  }
  $("top-meta").textContent = `${state.meta.n_games} games\n${state.meta.n_drives} drives\n${state.meta.n_scrimmage.toLocaleString()} scrimmage plays`;
}

$("season").addEventListener("change", (e) => {
  state.season = e.target.value;
  state.cell = null;
  refresh();
});
$("garbage").addEventListener("change", (e) => {
  state.excludeGarbage = e.target.checked;
  refresh();
});
$("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  state.tab = btn.dataset.tab;
  for (const b of $("tabs").querySelectorAll("button")) b.classList.toggle("on", b === btn);
  refresh();
});

async function refresh() {
  renderFilters();
  const overview = await get(`/api/overview?${qs()}`);
  renderKpis(overview);
  if (state.tab === "playbook") await renderPlaybook();
  else if (state.tab === "drives") await renderDrives();
  else if (state.tab === "sequence") await renderSequence();
  else if (state.tab === "situations") await renderSituations();
  else await renderEras();
  await renderPlays();
}

function renderKpis(o) {
  const items = [
    ["Plays", o.plays?.toLocaleString?.() || o.plays],
    ["Pass rate", pct(o.pass_rate)],
    ["Success", pct(o.success_rate)],
    ["Explosive", pct(o.explosive_rate)],
    ["Yds / play", num(o.yards_per_play)],
    ["1st-down pass", pct(o.first_down_pass_rate)],
    ["Pts / drive", num(o.points_per_drive)],
    ["3-and-out", pct(o.three_and_out_rate)],
  ];
  $("kpis").innerHTML = items
    .map(([label, val]) => `<div class="kpi"><b>${val ?? "—"}</b><span>${label}</span></div>`)
    .join("");
}

async function renderPlaybook() {
  const data = await get(`/api/down-distance?${qs()}`);
  const map = new Map(data.rows.map((r) => [`${r.down}-${r.distance_bucket}`, r]));
  let html = `<div class="panel"><div class="heat">
    <div></div>${BUCKETS.map((b) => `<div class="lab">${b} yds</div>`).join("")}`;
  for (const down of [1, 2, 3, 4]) {
    html += `<div class="lab">${down}${["st", "nd", "rd", "th"][down - 1]}</div>`;
    for (const bucket of BUCKETS) {
      const row = map.get(`${down}-${bucket}`);
      if (!row || !row.n) {
        html += `<div class="cell empty"><small>n=0</small></div>`;
        continue;
      }
      const on = state.cell && state.cell.down === down && state.cell.bucket === bucket;
      html += `<button class="cell ${on ? "on" : ""}" style="background:${mixColor(row.pass_rate)}"
        data-down="${down}" data-bucket="${bucket}">
        <b>${pct(row.pass_rate)}</b>
        <small>n=${row.n} · ${num(row.yards_per_play)} yds · suc ${pct(row.success_rate)}</small>
      </button>`;
    }
  }
  html += `</div>
    <p style="color:var(--muted);font-size:12px;margin:12px 0 0">
      Color is pass rate (green = run-heavy, orange = pass-heavy). Click a cell to filter the play list.
    </p></div>`;
  $("main").innerHTML = html;
  $("main").querySelectorAll(".cell[data-down]").forEach((el) => {
    el.addEventListener("click", () => {
      const down = Number(el.dataset.down);
      const bucket = el.dataset.bucket;
      if (state.cell && state.cell.down === down && state.cell.bucket === bucket) state.cell = null;
      else state.cell = { down, bucket };
      renderPlaybook().then(renderPlays);
    });
  });
}

async function renderDrives() {
  const { games } = await get(`/api/games?${qs()}`);
  if (!state.selectedGame && games.length) state.selectedGame = games[games.length - 1].game_id;
  const selected = games.find((g) => g.game_id === state.selectedGame) || games[0];
  let html = `<div class="games">
    <div class="panel game-list">${games
      .map((g) => {
        const on = selected && g.game_id === selected.game_id;
        return `<button class="game ${on ? "on" : ""}" data-id="${g.game_id}">
          <div class="when">${g.date} · ${g.era} · ${g.home_away}</div>
          <div><b>${g.result}</b> ${g.team_score}-${g.opp_score} vs ${g.opponent_abbrev || g.opponent}</div>
          <div class="when">${g.n_plays} plays · pass ${pct(g.pass_rate)}</div>
        </button>`;
      })
      .join("")}</div>
    <div class="panel" id="drive-panel">Select a game</div>
  </div>`;
  $("main").innerHTML = html;
  $("main").querySelectorAll(".game").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.selectedGame = btn.dataset.id;
      await renderDrives();
      await renderPlays();
    });
  });
  if (selected) await fillDrivePanel(selected.game_id);
}

async function fillDrivePanel(gameId) {
  const detail = await get(`/api/game/${gameId}`);
  const g = detail.game;
  let html = `<div style="margin-bottom:12px">
    <div class="kicker">${g.date} · ${g.era}</div>
    <h2 style="margin:4px 0 0;font-family:'Barlow Condensed',sans-serif;text-transform:uppercase">
      ${g.result} ${g.team_score}–${g.opp_score} vs ${g.opponent}
    </h2>
  </div>`;
  for (const d of detail.drives) {
    const start = d.start_yards_to_endzone ?? 75;
    const yards = Number(d.yards || 0);
    const left = Math.max(0, 100 - start);
    const width = Math.max(2, Math.min(100 - left, Math.abs(yards)));
    html += `<article class="drive">
      <div class="drive-meta">
        <span>Drive ${d.drive_number} · ${d.start_text || ""} → ${d.result}</span>
        <span>${d.scrimmage_plays || d.offensive_plays || 0} plays · ${d.yards ?? 0} yds · ${d.time_elapsed || ""}</span>
      </div>
      <div class="field"><div class="bar" style="left:${left}%;width:${width}%;background:${resultColor(d.result)}"></div></div>
      ${(d.plays || [])
        .filter((p) => p.scrimmage)
        .map(
          (p) => `<div class="play-line">
            <span>${p.down}&amp;${p.distance} ${p.clock || ""}</span>
            <span class="call ${p.play_call || ""}">${p.play_call || p.play_detail || ""}</span>
            <span>${p.description || ""}</span>
            <span>${p.yards ?? ""}</span>
          </div>`
        )
        .join("")}
    </article>`;
  }
  $("drive-panel").innerHTML = html;
}

async function renderSequence() {
  const s = await get(`/api/sequencing?${qs()}`);
  const cards = [
    ["After a run", s.after_run],
    ["After a pass", s.after_pass],
    ["After success", s.after_success],
    ["After failure", s.after_fail],
    ["After explosive (15+)", s.after_explosive],
    ["After stuffed run (≤1)", s.after_run_stuffed],
    ["After incompletion", s.after_incompletion],
  ];
  $("main").innerHTML = `<div class="seq">${cards
    .map(
      ([label, v]) => `<div class="card">
        <div class="kicker">${label}</div>
        <b style="font-size:32px;font-family:'Barlow Condensed',sans-serif">${pct(v.pass_rate)} pass</b>
        <div style="color:var(--muted);margin-top:6px">${v.n} plays · run ${pct(v.run_rate)} · success ${pct(v.success_rate)}</div>
      </div>`
    )
    .join("")}</div>`;
}

async function renderSituations() {
  const { rows } = await get(`/api/situations?${qs()}`);
  $("main").innerHTML = `<div class="sits">
    <div class="sit-row head"><div>Situation</div><div>n</div><div>Pass</div><div>Success</div><div>Expl.</div><div>Yds</div></div>
    ${rows
      .map(
        (r) => `<div class="sit-row">
          <div>${r.label}</div><div>${r.n}</div><div>${pct(r.pass_rate)}</div>
          <div>${pct(r.success_rate)}</div><div>${pct(r.explosive_rate)}</div><div>${num(r.yards_per_play)}</div>
        </div>`
      )
      .join("")}
  </div>`;
}

async function renderEras() {
  const { rows } = await get("/api/eras?" + qs());
  $("main").innerHTML = `<div class="eras-table">
    <div class="era-row head"><div>Era</div><div>Pass</div><div>1st pass</div><div>Success</div><div>Pts/drv</div><div>3-and-out</div></div>
    ${rows
      .map(
        (r) => `<div class="era-row">
          <div><b>${r.era}</b><div style="color:var(--muted)">${r.role} · ${r.seasons.join("–")} · ${r.games} g / ${r.plays} p</div></div>
          <div>${pct(r.pass_rate)}</div><div>${pct(r.first_down_pass_rate)}</div>
          <div>${pct(r.success_rate)}</div><div>${num(r.points_per_drive)}</div><div>${pct(r.three_and_out_rate)}</div>
        </div>`
      )
      .join("")}
  </div>`;
}

async function renderPlays() {
  const p = new URLSearchParams(qs());
  if (state.cell) {
    p.set("down", state.cell.down);
    p.set("distance_bucket", state.cell.bucket);
  }
  if (state.tab === "drives" && state.selectedGame) p.set("game_id", state.selectedGame);
  p.set("limit", "80");
  const data = await get(`/api/plays?${p.toString()}`);
  $("plays-count").textContent = `${data.total.toLocaleString()} matching`;
  $("plays-title").textContent = state.cell
    ? `Plays · ${state.cell.down} & ${state.cell.bucket}`
    : "Plays";
  $("plays-body").innerHTML = data.plays
    .map(
      (pl) => `<tr>
        <td>${pl.date || ""}</td>
        <td>${pl.opponent || ""}</td>
        <td>${pl.drive_number || ""}</td>
        <td>${pl.down || ""}&amp;${pl.distance || ""} Q${pl.period || ""} ${pl.clock || ""}</td>
        <td class="call ${pl.play_call || ""}">${pl.play_call || pl.play_detail || ""}</td>
        <td>${pl.yards ?? ""}</td>
        <td class="desc">${pl.description || ""}</td>
      </tr>`
    )
    .join("");
}

boot().catch((err) => {
  $("main").innerHTML = `<div class="panel">${err.message}</div>`;
});
