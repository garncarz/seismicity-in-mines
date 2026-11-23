const $ = (selector) => document.querySelector(selector);
const panelSelect = $("#panel-select");
const notice = $("#notice");
const map = L.map("map").setView([49.85, 18.5], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);
const panelLayer = L.featureGroup().addTo(map);
const eventLayer = L.layerGroup().addTo(map);
map.createPane("coordinateGridPane");
map.getPane("coordinateGridPane").style.zIndex = 350;
const coordinateGridLayer = L.geoJSON(null, {
  pane: "coordinateGridPane",
  style: { color: "#526b78", weight: 1, dashArray: "3 6", opacity: 0.62 },
  onEachFeature: (feature, layer) => {
    const { axis, value } = feature.properties;
    layer.bindTooltip(`${axis} ${formatNumber(value, 0)} m`, {
      permanent: true,
      direction: "center",
      className: "coordinate-grid-label",
    });
  },
});
const previewLayer = L.layerGroup().addTo(map);
let panels = [];
let editingId = null;
let previewValid = false;
let energyChart;
let timeChart;
let coordinateGridRequest = 0;

const formatNumber = (value, fractionDigits = 2) =>
  value === null || value === undefined ? "—" :
    Number(value).toLocaleString(undefined, { maximumFractionDigits: fractionDigits });

function showNotice(message) {
  notice.textContent = message;
  notice.classList.remove("hidden");
}

function clearNotice() {
  notice.textContent = "";
  notice.classList.add("hidden");
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(`Server returned an unexpected response (${response.status}).`);
  }
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
  return body;
}

function coordinateGridSpacing() {
  const zoom = map.getZoom();
  if (zoom >= 17) return 100;
  if (zoom >= 16) return 250;
  if (zoom >= 14) return 500;
  if (zoom >= 12) return 1000;
  if (zoom >= 10) return 2500;
  if (zoom >= 8) return 5000;
  return 10000;
}

async function refreshCoordinateGrid() {
  if (!$("#show-coordinate-grid").checked) return;
  const requestId = ++coordinateGridRequest;
  const bounds = map.getBounds();
  const query = new URLSearchParams({
    west: bounds.getWest(),
    south: bounds.getSouth(),
    east: bounds.getEast(),
    north: bounds.getNorth(),
    spacing: coordinateGridSpacing(),
  });
  try {
    const result = await requestJson(`/api/coordinate-grid?${query}`);
    if (requestId !== coordinateGridRequest || !$("#show-coordinate-grid").checked) return;
    coordinateGridLayer.clearLayers();
    coordinateGridLayer.addData(result);
  } catch (error) {
    if (requestId === coordinateGridRequest) showNotice(error.message);
  }
}

function setPreviewState(valid) {
  previewValid = valid;
  $("#save-panel").disabled = !valid;
}

function fitPanel(panel) {
  panelLayer.clearLayers();
  if (!panel) return;
  const monitoring = L.geoJSON(panel.monitoring_area, {
    style: { color: "#d68a36", weight: 2, dashArray: "6 5", fillColor: "#e9b675", fillOpacity: 0.12 },
  });
  const boundary = L.geoJSON(panel.boundary, {
    style: { color: "#176f86", weight: 3, fillColor: "#52a7af", fillOpacity: 0.13 },
  });
  panelLayer.addLayer(monitoring);
  panelLayer.addLayer(boundary);
  const bounds = panelLayer.getBounds();
  if (bounds.isValid()) map.fitBounds(bounds.pad(0.13));
}

function addEventPopup(event, marker) {
  const container = document.createElement("div");
  const heading = document.createElement("strong");
  heading.textContent = event.datetime.replace("T", " ");
  const details = document.createElement("p");
  details.textContent = `Energy: ${formatNumber(event.energy)} · Magnitude: ${formatNumber(event.magnitude)} · Z: ${formatNumber(event.z_m)} m`;
  const raw = document.createElement("pre");
  raw.textContent = JSON.stringify(event.attributes, null, 2);
  container.append(heading, details, raw);
  marker.bindPopup(container);
}

function magnitudeColor(magnitude, minimum, maximum) {
  if (magnitude === null || magnitude === undefined) return "#6b7280";
  if (minimum === maximum) return "#b91c1c";
  const ratio = Math.max(0, Math.min(1, (magnitude - minimum) / (maximum - minimum)));
  const lightness = 82 - ratio * 42;
  return `hsl(4, 76%, ${lightness}%)`;
}

function drawEvents(events) {
  eventLayer.clearLayers();
  const magnitudes = events.map((e) => e.magnitude).filter((value) => value !== null);
  const minMagnitude = magnitudes.length ? Math.min(...magnitudes) : 0;
  const maxMagnitude = magnitudes.length ? Math.max(...magnitudes) : 0;
  const energies = events.map((e) => e.energy).filter((value) => value > 0);
  const minLogEnergy = energies.length ? Math.log10(Math.min(...energies)) : 0;
  const maxLogEnergy = energies.length ? Math.log10(Math.max(...energies)) : 0;
  for (const event of events) {
    const logEnergy = event.energy > 0 ? Math.log10(event.energy) : minLogEnergy;
    const ratio = maxLogEnergy === minLogEnergy ? 0.5 :
      (logEnergy - minLogEnergy) / (maxLogEnergy - minLogEnergy);
    const marker = L.circleMarker([event.latitude, event.longitude], {
      radius: 4 + ratio * 6,
      color: magnitudeColor(event.magnitude, minMagnitude, maxMagnitude),
      fillOpacity: 0.76,
      weight: 1,
    });
    addEventPopup(event, marker);
    marker.addTo(eventLayer);
  }
}

function updateStatistics(stats) {
  $("#stat-count").textContent = formatNumber(stats.count, 0);
  $("#stat-energy").textContent = formatNumber(stats.total_energy);
  $("#stat-mean").textContent = formatNumber(stats.mean_magnitude);
  $("#stat-max-mag").textContent = formatNumber(stats.max_magnitude);
  $("#stat-max-energy").textContent = formatNumber(stats.max_energy);
  $("#chart-empty").textContent = stats.count ? "" : "No events match this panel and filter selection.";
  if (energyChart) energyChart.destroy();
  if (timeChart) timeChart.destroy();
  energyChart = new Chart($("#energy-chart"), {
    type: "bar",
    data: {
      labels: stats.energy_distribution.map((item) => item.bin),
      datasets: [{ label: "Events", data: stats.energy_distribution.map((item) => item.count), backgroundColor: "#4b9ba0" }],
    },
    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }, plugins: { legend: { display: false } } },
  });
  timeChart = new Chart($("#time-chart"), {
    type: "bar",
    data: {
      labels: stats.timeline.map((item) => item.month.slice(0, 7)),
      datasets: [
        { label: "Events / month", data: stats.timeline.map((item) => item.count), backgroundColor: "#77aeb2", yAxisID: "events" },
        { type: "line", label: "Cumulative energy", data: stats.timeline.map((item) => item.cumulative_energy), borderColor: "#d2743b", backgroundColor: "#d2743b", pointRadius: 1, yAxisID: "energy" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        events: { beginAtZero: true, position: "left", ticks: { precision: 0 } },
        energy: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false } },
      },
    },
  });
}

function filterQuery() {
  const panelId = panelSelect.value;
  if (!panelId) throw new Error("Select a mining panel first.");
  const query = new URLSearchParams({ panel_id: panelId, period: $("#period").value });
  if ($("#period").value === "range") {
    if (!$("#start-date").value || !$("#end-date").value) throw new Error("Choose both dates for the custom interval.");
    query.set("start", $("#start-date").value);
    query.set("end", $("#end-date").value);
  }
  if ($("#min-energy").value) query.set("min_energy", $("#min-energy").value);
  if ($("#min-magnitude").value) query.set("min_magnitude", $("#min-magnitude").value);
  return query;
}

async function applyFilters() {
  clearNotice();
  try {
    const query = filterQuery();
    const [events, stats] = await Promise.all([
      requestJson(`/api/events?${query}`),
      requestJson(`/api/statistics?${query}`),
    ]);
    drawEvents(events.events);
    updateStatistics(stats);
    $("#event-count").textContent = `${formatNumber(stats.count, 0)} matching events · ${formatNumber(events.returned, 0)} shown${events.truncated ? ` (map limited to ${formatNumber(events.limit, 0)})` : ""}`;
  } catch (error) {
    showNotice(error.message);
  }
}

async function loadPanels(selectedId = null) {
  panels = await requestJson("/api/panels");
  panelSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = panels.length ? "Choose a panel…" : "No panels defined";
  panelSelect.append(placeholder);
  for (const panel of panels) {
    const option = document.createElement("option");
    option.value = panel.id;
    option.textContent = panel.seam ? `${panel.identifier} · ${panel.seam}` : panel.identifier;
    panelSelect.append(option);
  }
  const defaultPanel = panels.find((panel) => panel.identifier === "138 708") || panels[0];
  const requestedPanel = selectedId
    ? panels.find((panel) => String(panel.id) === String(selectedId))
    : defaultPanel;
  panelSelect.value = requestedPanel ? String(requestedPanel.id) : "";
  selectPanel();
}

function selectPanel() {
  const panel = panels.find((item) => String(item.id) === panelSelect.value);
  fitPanel(panel);
  $("#panel-summary").textContent = panel
    ? `Monitoring boundary: ${formatNumber(panel.buffer_m, 0)} m buffer · Mining: ${panel.mining_start || "not set"} to ${panel.mining_end || "not set"}`
    : "";
  eventLayer.clearLayers();
  if (panel) applyFilters();
  else {
    $("#event-count").textContent = "Select a panel to begin.";
    updateStatistics({ count: 0, total_energy: 0, mean_magnitude: null, max_magnitude: null, max_energy: null, energy_distribution: [], timeline: [] });
  }
}

async function previewPanel() {
  clearNotice();
  setPreviewState(false);
  previewLayer.clearLayers();
  try {
    const preview = await requestJson("/api/panels/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: $("#panel-description").value, seam: $("#panel-seam").value }),
    });
    L.geoJSON(preview.monitoring_geojson, {
      style: { color: "#d68a36", weight: 2, dashArray: "6 5", fillColor: "#e9b675", fillOpacity: 0.12 },
    }).addTo(previewLayer);
    L.geoJSON(preview.boundary_geojson, {
      style: { color: "#176f86", weight: 3, fillColor: "#52a7af", fillOpacity: 0.13 },
    }).addTo(previewLayer);
    const bounds = previewLayer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.13));
    $("#panel-preview-summary").textContent =
      `Porub ${preview.identifier} · ${preview.vertices.length} vertices · ${formatNumber(preview.buffer_m, 1)} m buffer · ${preview.mining_start || "start not set"} – ${preview.mining_end || "end not set"}`;
    setPreviewState(true);
    $("#save-panel").textContent = editingId ? "Update panel" : "Save panel";
  } catch (error) {
    showNotice(error.message);
    $("#panel-preview-summary").textContent = "";
  }
}

function clearEditor() {
  editingId = null;
  previewLayer.clearLayers();
  $("#panel-description").value = "";
  $("#panel-seam").value = "";
  $("#panel-preview-summary").textContent = "";
  $("#save-panel").textContent = "Save panel";
  $("#cancel-edit").classList.add("hidden");
  setPreviewState(false);
}

async function savePanel() {
  if (!previewValid) return;
  const method = editingId ? "PUT" : "POST";
  const url = editingId ? `/api/panels/${editingId}` : "/api/panels";
  try {
    const saved = await requestJson(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: $("#panel-description").value, seam: $("#panel-seam").value }),
    });
    clearEditor();
    await loadPanels(saved.id);
    clearNotice();
  } catch (error) {
    showNotice(error.message);
  }
}

async function editPanel() {
  const panelId = panelSelect.value;
  if (!panelId) return showNotice("Select a panel to edit.");
  try {
    const panel = await requestJson(`/api/panels/${panelId}`);
    editingId = panel.id;
    $("#panel-description").value = panel.description;
    $("#panel-seam").value = panel.seam || "";
    $("#cancel-edit").classList.remove("hidden");
    await previewPanel();
  } catch (error) {
    showNotice(error.message);
  }
}

async function deletePanel() {
  const panelId = panelSelect.value;
  const panel = panels.find((item) => String(item.id) === panelId);
  if (!panel || !window.confirm(`Delete panel ${panel.identifier}?`)) return;
  try {
    await requestJson(`/api/panels/${panelId}`, { method: "DELETE" });
    await loadPanels();
    clearNotice();
  } catch (error) {
    showNotice(error.message);
  }
}

async function importWorkbook(event) {
  event.preventDefault();
  const file = $("#import-file").files[0];
  if (!file) return;
  const result = $("#import-result");
  result.textContent = "Importing workbook…";
  const form = new FormData($("#import-form"));
  try {
    const stats = await requestJson("/api/import", { method: "POST", body: form });
    const parts = [
      stats.already_imported ? "This exact file was already imported." : `Imported ${stats.filename} (${stats.source_type}).`,
      `${stats.accepted_rows} accepted`,
      `${stats.skipped_rows} skipped`,
      `${stats.duplicate_events} duplicate events`,
      `${stats.warnings} warnings`,
    ];
    result.textContent = parts.join(" · ");
    if (stats.issues && stats.issues.length) {
      const list = document.createElement("ul");
      list.className = "issue-list";
      for (const issue of stats.issues) {
        const item = document.createElement("li");
        item.textContent = `Row ${issue.row}: ${issue.message}`;
        list.append(item);
      }
      result.append(list);
    }
    if (panelSelect.value) applyFilters();
  } catch (error) {
    result.textContent = error.message;
  }
}

$("#period").addEventListener("change", () => $("#date-range").classList.toggle("hidden", $("#period").value !== "range"));
$("#apply-filters").addEventListener("click", applyFilters);
panelSelect.addEventListener("change", selectPanel);
panelSelect.addEventListener("change", () => {
  if (editingId && String(editingId) !== panelSelect.value) clearEditor();
});
$("#preview-panel").addEventListener("click", previewPanel);
$("#save-panel").addEventListener("click", savePanel);
$("#cancel-edit").addEventListener("click", clearEditor);
$("#new-panel").addEventListener("click", () => {
  clearEditor();
  $("#panel-management").open = true;
  $("#panel-description").focus();
});
$("#import-form").addEventListener("submit", importWorkbook);
$("#panel-description").addEventListener("input", () => {
  if (!previewValid) return;
  setPreviewState(false);
  previewLayer.clearLayers();
  $("#panel-preview-summary").textContent = "Description changed; preview the panel again before saving.";
});
$("#show-coordinate-grid").addEventListener("change", (event) => {
  coordinateGridRequest += 1;
  if (event.target.checked) {
    map.addLayer(coordinateGridLayer);
    refreshCoordinateGrid();
  } else {
    coordinateGridLayer.clearLayers();
    map.removeLayer(coordinateGridLayer);
  }
});
map.on("moveend", refreshCoordinateGrid);

$("#edit-selected").addEventListener("click", editPanel);
$("#delete-selected").addEventListener("click", deletePanel);

loadPanels().catch((error) => showNotice(error.message));
