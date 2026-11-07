// Lobby page: create a game, list the games on this server (specification 6.3).
"use strict";

const $ = (id) => document.getElementById(id);
let options = { worlds: [], scenarios: [], seat_kinds: ["human"] };

function showError(text) {
  const bar = $("error");
  bar.textContent = text || "";
  bar.style.display = text ? "block" : "none";
}

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText);
  return data;
}

function seatRow(index, kind) {
  const row = document.createElement("div");
  row.className = "seat-row";
  const label = document.createElement("span");
  label.textContent = `Seat ${index + 1}`;
  const name = document.createElement("input");
  name.placeholder = kind === "human" ? "filled in by the player" : `Bot ${index + 1}`;
  name.className = "seat-name";
  const select = document.createElement("select");
  select.className = "seat-kind";
  for (const k of options.seat_kinds) select.add(new Option(k, k, false, k === kind));
  select.onchange = () => { name.placeholder = select.value === "human" ? "filled in by the player" : `Bot ${index + 1}`; };
  row.append(label, select, name);
  return row;
}

function renumber() {
  [...$("seats").children].forEach((row, i) => { row.firstChild.textContent = `Seat ${i + 1}`; });
}

async function loadOptions() {
  options = await api("/api/options");
  const world = $("world");
  world.innerHTML = "";
  for (const w of options.worlds) world.add(new Option(`${w.scenario} / ${w.id}`, `file:${w.file}`));
  for (const s of options.scenarios) world.add(new Option(`${s}: generate a new world`, `scenario:${s}`));
  world.onchange = () => { $("world-seed-row").style.display = world.value.startsWith("scenario:") ? "inline" : "none"; };
  $("seats").innerHTML = "";
  $("seats").append(seatRow(0, "human"), seatRow(1, "cooperative"), seatRow(2, "selfish"));
}

async function loadGames() {
  const games = await api("/api/games");
  const box = $("games");
  if (!games.length) { box.innerHTML = '<p class="muted">No games yet.</p>'; return; }
  const table = document.createElement("table");
  table.innerHTML = "<tr><th>Game</th><th>World</th><th>Status</th><th>Seats</th><th>Actions</th><th>Created</th><th></th></tr>";
  for (const g of games) {
    const tr = table.insertRow();
    const seats = g.players.map((p, i) => `${p} (${g.seats[i]})`).join(", ");
    [g.id, g.world, g.status, seats, g.actions, new Date(g.created * 1000).toLocaleString()].forEach((v) => {
      tr.insertCell().textContent = v;
    });
    const link = document.createElement("a");
    link.href = `/game/${g.id}`;
    link.textContent = "open";
    const cell = tr.insertCell();
    cell.append(link);
    if (["finished", "ended"].includes(g.status)) {  // the debrief can be reopened later (specification 10)
      const debrief = document.createElement("a");
      debrief.href = `/game/${g.id}/debrief`;
      debrief.textContent = "debrief";
      cell.append(" \u00b7 ", debrief);
    }
  }
  box.innerHTML = "";
  box.append(table);
}

$("add-seat").onclick = () => { $("seats").append(seatRow($("seats").children.length, "selfish")); };
$("remove-seat").onclick = () => { const s = $("seats"); if (s.children.length > 1) s.lastChild.remove(); renumber(); };
$("refresh").onclick = () => loadGames().catch((e) => showError(e.message));

$("create").onsubmit = async (event) => {
  event.preventDefault();
  showError("");
  const choice = $("world").value;
  const number = (id) => ($(id).value === "" ? null : Number($(id).value));
  const body = {
    seats: [...$("seats").children].map((row) => ({
      kind: row.querySelector(".seat-kind").value, name: row.querySelector(".seat-name").value,
    })),
    seed: number("seed"),
    overrides: $("overrides").value,
    join_password: $("join-password").value,
    spectator_password: $("spectator-password").value,
  };
  if (choice.startsWith("file:")) body.world = choice.slice(5);
  else { body.scenario = choice.slice(9); body.world_seed = number("world-seed"); }
  const button = event.submitter;
  button.disabled = true;
  button.textContent = "Creating...";
  try {
    const created = await api("/api/games", body);
    localStorage.setItem(`nv:${created.game}:host`, created.host_token);
    const base = `${location.origin}/game/${created.game}`;
    $("join-link").value = base;
    $("host-link").value = `${base}#host=${created.host_token}`;
    $("open-game").href = `/game/${created.game}`;
    $("created").style.display = "block";
    loadGames();
  } catch (e) {
    showError(e.message);
  } finally {
    button.disabled = false;
    button.textContent = "Create game";
  }
};

loadOptions().then(loadGames).catch((e) => showError(e.message));
