const canvas = document.querySelector("#display");
const context = canvas.getContext("2d", { alpha: false });

const elements = {
  blockHeight: document.querySelector("#block-height"),
  brightness: document.querySelector("#brightness"),
  brightnessValue: document.querySelector("#brightness-value"),
  clock: document.querySelector("#clock"),
  error: document.querySelector("#error-banner"),
  frameSummary: document.querySelector("#frame-summary"),
  grid: document.querySelector("#led-grid"),
  litPixels: document.querySelector("#lit-pixels"),
  liveClock: document.querySelector("#live-clock"),
  logicalSize: document.querySelector("#logical-size"),
  moscowTime: document.querySelector("#moscow-time"),
  price: document.querySelector("#price"),
  reset: document.querySelector("#reset-frame"),
  sourceFile: document.querySelector("#source-file"),
  sourceStatus: document.querySelector("#source-status"),
  statusPixel: document.querySelector("#status-pixel"),
  ticker: document.querySelector("#ticker"),
  viewDashboard: document.querySelector("#view-dashboard"),
  viewTicker: document.querySelector("#view-ticker"),
};

const defaults = {
  blockHeight: "900736",
  moscowTime: "912",
  price: "109600",
  ticker: "BITCOIN NETWORK ONLINE",
};

const state = {
  brightness: 10,
  config: null,
  lastRevision: null,
  tickerTimer: null,
  tickerWidth: 0,
  tickerX: 0,
  view: "dashboard",
};

function dimColor(color, level) {
  const clamped = Math.max(1, Math.min(Number(level), 10));
  if (clamped === 10) {
    return color;
  }
  const fraction = clamped / 10;
  const channel = (shift) => {
    const scaled = ((color >> shift) & 0xff) * fraction;
    return scaled > 0 ? Math.max(Math.trunc(scaled), 1) : 0;
  };
  return (channel(16) << 16) | (channel(8) << 8) | channel(0);
}

function colorToCss(color) {
  return `#${color.toString(16).padStart(6, "0")}`;
}

function currentClock() {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
}

function glyphFor(font, character) {
  return font.glyphs[String(character.codePointAt(0))]
    ?? font.glyphs["0"]
    ?? null;
}

function layoutText(font, text) {
  const glyphs = [];
  let cursorX = 0;
  let top = 0;
  let bottom = 0;
  let right = 0;

  for (const character of text) {
    const glyph = glyphFor(font, character);
    if (!glyph) {
      continue;
    }
    const glyphTop = -glyph.height - glyph.dy;
    glyphs.push({ glyph, x: cursorX + glyph.dx, y: glyphTop });
    top = Math.min(top, glyphTop);
    bottom = Math.max(bottom, -glyph.dy);
    right = Math.max(right, cursorX + glyph.shiftX, cursorX + glyph.dx + glyph.width);
    cursorX += glyph.shiftX;
  }

  return {
    glyphs,
    top,
    width: right,
    height: bottom - top,
  };
}

function setPixel(frame, x, y, color) {
  const { width, height } = state.config.display;
  if (x < 0 || y < 0 || x >= width || y >= height) {
    return;
  }
  frame[y * width + x] = color;
}

function drawText(frame, font, text, x, y, color, scale = 1) {
  const layout = layoutText(font, text);
  for (const item of layout.glyphs) {
    const glyphX = x + item.x * scale;
    const glyphY = y + (item.y - layout.top) * scale;
    for (let row = 0; row < item.glyph.rows.length; row += 1) {
      const pixels = item.glyph.rows[row];
      for (let column = 0; column < pixels.length; column += 1) {
        if (pixels[column] !== "1") {
          continue;
        }
        for (let scaleY = 0; scaleY < scale; scaleY += 1) {
          for (let scaleX = 0; scaleX < scale; scaleX += 1) {
            setPixel(
              frame,
              glyphX + column * scale + scaleX,
              glyphY + row * scale + scaleY,
              color,
            );
          }
        }
      }
    }
  }
  return layout;
}

function drawLayer(frame, layer, text, override = {}) {
  const font = state.config.fonts[layer.font];
  if (!font || !text) {
    return { width: 0, height: 0 };
  }
  const x = override.x ?? layer.position[0];
  const y = override.y ?? Math.max(0, layer.position[1]);
  return drawText(
    frame,
    font,
    text,
    x,
    y,
    dimColor(layer.color, state.brightness),
    layer.scale,
  );
}

function renderPanel(frame) {
  const { width, height } = state.config.display;
  const scale = 10;
  const useGrid = elements.grid.checked;
  canvas.width = width * scale;
  canvas.height = height * scale;
  context.fillStyle = "#020303";
  context.fillRect(0, 0, canvas.width, canvas.height);

  let lit = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const color = frame[y * width + x];
      if (color !== 0) {
        lit += 1;
      }
      if (useGrid) {
        context.fillStyle = color === 0 ? "#111515" : colorToCss(color);
        context.beginPath();
        context.arc(
          x * scale + scale / 2,
          y * scale + scale / 2,
          color === 0 ? 2.55 : 3.25,
          0,
          Math.PI * 2,
        );
        context.fill();
        if (color !== 0) {
          context.fillStyle = "rgba(255, 255, 255, 0.22)";
          context.beginPath();
          context.arc(x * scale + 4, y * scale + 4, 1.1, 0, Math.PI * 2);
          context.fill();
        }
      } else {
        context.fillStyle = color === 0 ? "#020303" : colorToCss(color);
        context.fillRect(x * scale, y * scale, scale, scale);
      }
    }
  }

  elements.litPixels.textContent = `${lit} LED${lit === 1 ? "" : "s"} lit`;
}

function render() {
  if (!state.config) {
    return;
  }

  const { layers } = state.config.btc;
  const frame = new Uint32Array(
    state.config.display.width * state.config.display.height,
  );

  drawLayer(frame, layers.price, elements.price.value);
  drawLayer(frame, layers.blockheight, elements.blockHeight.value);
  drawLayer(frame, layers.moscow, elements.moscowTime.value);

  if (state.view === "ticker") {
    const tickerLayout = drawLayer(
      frame,
      layers.ticker,
      elements.ticker.value,
      { x: state.tickerX },
    );
    state.tickerWidth = tickerLayout.width * layers.ticker.scale;
  } else {
    drawLayer(frame, layers.time, elements.clock.value);
  }

  if (elements.statusPixel.checked) {
    drawLayer(frame, layers.status_pixel, ".");
  }

  renderPanel(frame);
  elements.frameSummary.textContent = state.view === "ticker"
    ? `Ticker · BTC ${elements.price.value} · block ${elements.blockHeight.value}`
    : `BTC ${elements.price.value} · block ${elements.blockHeight.value}`;
  canvas.setAttribute(
    "aria-label",
    state.view === "ticker"
      ? `BlockTron display showing bitcoin price ${elements.price.value}, block ${elements.blockHeight.value}, Moscow time ${elements.moscowTime.value}, and scrolling ticker ${elements.ticker.value}`
      : `BlockTron display showing bitcoin price ${elements.price.value}, block ${elements.blockHeight.value}, Moscow time ${elements.moscowTime.value}, and time ${elements.clock.value}`,
  );
}

function setStatus(stateName, message) {
  elements.sourceStatus.dataset.state = stateName;
  elements.sourceStatus.querySelector("strong").textContent = message;
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.hidden = false;
  setStatus("error", "Source error");
}

function clearError() {
  elements.error.hidden = true;
  elements.error.textContent = "";
}

function updateTickerTimer({ reset = false } = {}) {
  if (state.tickerTimer) {
    clearInterval(state.tickerTimer);
    state.tickerTimer = null;
  }
  if (reset) {
    state.tickerX = 0;
  }
  if (state.view !== "ticker" || !state.config) {
    return;
  }

  state.tickerTimer = setInterval(() => {
    state.tickerX -= 1;
    if (state.tickerX < -state.tickerWidth) {
      state.tickerX = state.config.display.width;
    }
    render();
  }, 90);
}

function setView(view) {
  state.view = view;
  elements.viewDashboard.checked = view === "dashboard";
  elements.viewTicker.checked = view === "ticker";
  updateTickerTimer({ reset: view === "ticker" });
  render();
}

function resetFrame() {
  elements.price.value = defaults.price;
  elements.blockHeight.value = defaults.blockHeight;
  elements.moscowTime.value = defaults.moscowTime;
  elements.ticker.value = defaults.ticker;
  elements.liveClock.checked = true;
  elements.clock.disabled = true;
  elements.clock.value = currentClock();
  elements.grid.checked = true;
  elements.statusPixel.checked = false;
  state.brightness = state.config.brightness;
  elements.brightness.value = String(state.brightness);
  elements.brightnessValue.value = String(state.brightness);
  setView("dashboard");
}

async function fetchConfig({ initial = false } = {}) {
  const response = await fetch("/api/config", { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) {
    state.lastRevision = payload.revision;
    throw new Error(payload.error ?? `Config request failed: ${response.status}`);
  }

  state.config = payload;
  state.lastRevision = payload.revision;

  if (initial) {
    state.brightness = payload.brightness;
    elements.brightness.value = String(state.brightness);
    elements.brightnessValue.value = String(state.brightness);
    elements.clock.value = currentClock();
  }

  elements.logicalSize.textContent =
    `${payload.display.width} × ${payload.display.height} px`;
  elements.sourceFile.textContent = payload.source.path;
  clearError();
  setStatus("ready", initial ? "Source synced" : "Source updated");
  updateTickerTimer();
  render();
}

async function pollRevision() {
  try {
    const response = await fetch("/api/revision", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    if (payload.revision !== state.lastRevision) {
      setStatus("loading", "Reloading source");
      await fetchConfig();
    }
  } catch (error) {
    showError(error.message);
  }
}

elements.viewDashboard.addEventListener("change", () => {
  if (elements.viewDashboard.checked) {
    setView("dashboard");
  }
});
elements.viewTicker.addEventListener("change", () => {
  if (elements.viewTicker.checked) {
    setView("ticker");
  }
});
for (const element of [
  elements.price,
  elements.blockHeight,
  elements.moscowTime,
  elements.clock,
]) {
  element.addEventListener("input", render);
}
elements.ticker.addEventListener("input", () => {
  state.tickerX = 0;
  render();
});
elements.liveClock.addEventListener("change", () => {
  elements.clock.disabled = elements.liveClock.checked;
  if (elements.liveClock.checked) {
    elements.clock.value = currentClock();
  }
  render();
});
elements.brightness.addEventListener("input", () => {
  state.brightness = Number(elements.brightness.value);
  elements.brightnessValue.value = String(state.brightness);
  render();
});
elements.grid.addEventListener("change", render);
elements.statusPixel.addEventListener("change", render);
elements.reset.addEventListener("click", resetFrame);

setInterval(() => {
  if (elements.liveClock.checked) {
    const nextClock = currentClock();
    if (nextClock !== elements.clock.value) {
      elements.clock.value = nextClock;
      render();
    }
  }
}, 1000);
setInterval(pollRevision, 1000);

elements.clock.disabled = true;
fetchConfig({ initial: true }).catch((error) => showError(error.message));
