// Editor de video — interfaz
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const mmss = (t) => { t = Math.max(0, t || 0); return `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`; };

const S = { proyectos: [], p: null, pieza: null, plan: null, sucio: false, poll: null, cfg: null, nuevo: { formato: "reel" } };

const FORMATOS = {
  reel: ["Reel", "Vertical 9:16, 30 a 60 s, una sola idea."],
  doble: ["Pantalla doble", "Arriba un gráfico o imagen, abajo vos hablando."],
  recortes: ["Recortes de YouTube", "De un video largo, de 3 a 5 reels independientes."],
};
const TRABAJOS = {
  transcribir: "Transcribiendo (la primera vez descarga el modelo de ~490 MB)…",
  candidatos: "La IA está buscando los mejores fragmentos…",
  plan: "La IA está armando el plan de cortes…",
  broll: "Generando imágenes de b-roll…",
  borrador: "Renderizando el borrador…",
  final: "Renderizando el video final…",
};

async function api(url, opts = {}) {
  const r = await fetch(url, {
    ...opts,
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {},
    body: opts.body && !(opts.body instanceof FormData) ? JSON.stringify(opts.body) : opts.body,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Error ${r.status}`);
  return data;
}
const fallo = (e) => alert(e.message || e);

// ---------- lista y navegación ----------

async function cargarLista() {
  S.proyectos = await api("/api/proyectos");
  $("#lista").innerHTML = S.proyectos.length
    ? S.proyectos.map((p) => `
      <div class="item ${S.p?.id === p.id ? "activo" : ""}" data-id="${p.id}">
        <div class="n">${esc(p.nombre)}</div>
        <div class="sutil chico">${FORMATOS[p.formato][0]} · ${new Date(p.creado * 1000).toLocaleDateString()}</div>
      </div>`).join("")
    : `<p class="sutil chico">Todavía no editaste ningún video.</p>`;
}
$("#lista").addEventListener("click", (e) => {
  const it = e.target.closest(".item");
  if (it) location.hash = it.dataset.id;
});
$("#btn-nuevo").onclick = () => (location.hash = "");
window.addEventListener("hashchange", ruta);

async function ruta() {
  if (S.sucio && !confirm("Tenés cambios sin guardar en el plan. ¿Salir igual?")) return;
  S.sucio = false;
  clearTimeout(S.poll);
  const id = location.hash.slice(1);
  if (!id) { S.p = null; vistaNuevo(); }
  else await abrir(id, true);
  cargarLista();
}

// ---------- nuevo proyecto ----------

function vistaNuevo() {
  const n = S.nuevo;
  $("#main").innerHTML = `<div class="contenido">
    <h1>Nuevo video</h1>
    <p class="sutil">Subí el video y elegí el formato. El original no se modifica nunca.</p>
    ${S.cfg && !conectado() ? `<div class="aviso">Conectá una cuenta (Claude o ChatGPT) para que la IA decida los cortes. <a href="#" id="ir-cfg" style="color:inherit">Conectar</a>.</div>` : ""}
    <div class="tarjeta">
      <div class="drop" id="drop">
        <div class="grande" id="drop-txt">${n.video ? "🎬 " + esc(n.video.name) : "Arrastrá el video acá o hacé clic"}</div>
        <div class="sutil chico">MP4, MOV, MKV, WEBM</div>
        <input type="file" id="f-video" accept="video/*" hidden>
      </div>
      <h3>Formato</h3>
      <div class="formatos">${Object.entries(FORMATOS).map(([k, [t, d]]) => `
        <div class="formato ${n.formato === k ? "sel" : ""}" data-f="${k}"><b>${t}</b><span class="sutil chico">${d}</span></div>`).join("")}
      </div>
      <label>Llamado a la acción (opcional)
        <input id="f-cta" placeholder='Ej: comentá "GUÍA" y te la mando' value="${esc(n.cta)}"></label>
      <label>Notas para la edición (opcional)
        <textarea id="f-notas" placeholder="Ej: ritmo tranquilo, el tema central es…">${esc(n.notas)}</textarea></label>
      <div id="f-imgs-wrap" ${n.formato === "doble" ? "" : "hidden"}>
        <label>Imágenes para la parte de arriba (PNG o JPG)
          <input type="file" id="f-imgs" accept="image/png,image/jpeg,image/webp" multiple></label>
      </div>
      <div class="fila fin"><span class="sutil chico" id="f-prog"></span>
        <button class="btn primario" id="f-crear" ${n.video ? "" : "disabled"}>Subir y transcribir</button></div>
    </div></div>`;
  const drop = $("#drop"), inp = $("#f-video");
  $("#ir-cfg")?.addEventListener("click", (e) => { e.preventDefault(); abrirConfig(); });
  const elegir = (f) => { if (f) { n.video = f; $("#drop-txt").textContent = "🎬 " + f.name; $("#f-crear").disabled = false; } };
  drop.onclick = () => inp.click();
  inp.onchange = () => elegir(inp.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("sobre"); };
  drop.ondragleave = () => drop.classList.remove("sobre");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("sobre"); elegir(e.dataTransfer.files[0]); };
  document.querySelectorAll(".formato").forEach((el) => (el.onclick = () => {
    n.formato = el.dataset.f; n.cta = $("#f-cta").value; n.notas = $("#f-notas").value; vistaNuevo();
  }));
  $("#f-crear").onclick = () => {
    const fd = new FormData();
    fd.append("video", n.video);
    fd.append("formato", n.formato);
    fd.append("cta", $("#f-cta").value);
    fd.append("notas", $("#f-notas").value);
    for (const f of $("#f-imgs")?.files || []) fd.append("imagenes", f);
    $("#f-crear").disabled = true;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/proyectos");
    xhr.upload.onprogress = (e) => ($("#f-prog").textContent = `Subiendo… ${Math.round((e.loaded / e.total) * 100)}%`);
    xhr.onload = () => {
      const d = JSON.parse(xhr.responseText || "{}");
      if (xhr.status >= 400) { alert(d.detail || "No se pudo subir"); $("#f-crear").disabled = false; return; }
      S.nuevo = { formato: "reel" };
      location.hash = d.id;
    };
    xhr.onerror = () => { alert("Se cortó la subida"); $("#f-crear").disabled = false; };
    xhr.send(fd);
  };
}

// ---------- proyecto ----------

async function abrir(id, reiniciar = false) {
  try { S.p = await api(`/api/proyectos/${id}`); }
  catch (e) { $("#main").innerHTML = `<div class="vacio-main">${esc(e.message)}</div>`; return; }
  const nums = S.p.piezas.map((x) => x.n);
  if (reiniciar || !nums.includes(S.pieza)) S.pieza = nums[0] ?? null;
  if (!S.sucio) S.plan = structuredClone(piezaActual()?.plan ?? null);
  vistaProyecto();
  vigilar();
}
const piezaActual = () => S.p?.piezas.find((x) => x.n === S.pieza);
const corriendo = () => S.p?.trabajo?.estado === "corriendo";

function vigilar() {
  clearTimeout(S.poll);
  if (!corriendo()) return;
  S.poll = setTimeout(async () => {
    const id = S.p.id;
    const d = await api(`/api/proyectos/${id}`).catch(() => null);
    if (!d || S.p?.id !== id) return;
    if (d.trabajo?.estado === "corriendo") {
      S.p.trabajo = d.trabajo;
      $("#banner").outerHTML = bannerHTML();
      vigilar();
    } else {
      const tipo = d.trabajo?.tipo;
      if (tipo === "plan" || tipo === "broll") S.sucio = false;
      await abrir(id);
    }
  }, 1500);
}

function bannerHTML() {
  const t = S.p.trabajo;
  if (!t) return `<div id="banner"></div>`;
  if (t.estado === "corriendo") {
    const seg = Math.round(Date.now() / 1000 - t.inicio);
    return `<div id="banner" class="banner"><span class="spin"></span>${TRABAJOS[t.tipo] || t.tipo}
      <span class="sutil chico">${seg}s</span>${t.log ? `<pre>${esc(t.log.trim().split("\n").slice(-4).join("\n"))}</pre>` : ""}</div>`;
  }
  if (t.estado === "error")
    return `<div id="banner" class="banner error"><b>Falló: ${esc(t.tipo)}.</b> ${esc(t.error)}
      ${t.tipo === "transcribir" ? `<button class="btn mini" data-acc="transcribir">Reintentar</button>` : ""}</div>`;
  return `<div id="banner"></div>`;
}

function vistaProyecto() {
  const p = S.p, tr = p.transcripcion;
  const ocupado = corriendo();
  const sinClave = S.cfg && !conectado();
  let html = `<div class="contenido">
    <div class="fila"><h1>${esc(p.nombre)}</h1><span class="etiqueta">${FORMATOS[p.formato][0]}</span>
      <span class="sutil chico">${mmss(p.duracion)} de original</span><span class="espacio"></span>
      <button class="btn ghost mini peligro" data-acc="borrar">Borrar proyecto</button></div>
    ${p.cta ? `<p class="sutil chico">Llamado a la acción: ${esc(p.cta)}</p>` : ""}
    ${bannerHTML()}
    <div class="tarjeta"><div class="paso ${tr ? "hecho" : ""}"><span class="num">1</span><b>Transcripción</b>
      ${tr ? `<span class="sutil chico">${tr.frases.length} frases · ${tr.palabras.length} palabras</span>` : `<span class="sutil chico">${ocupado ? "en curso…" : "pendiente"}</span>`}
    </div>
    ${tr ? `<details style="margin-top:10px"><summary class="sutil chico">Ver transcripción</summary>
      <div class="frases">${tr.frases.map((f) => `<div><span>${mmss(f.s)}</span>${esc(f.texto)}</div>`).join("")}</div></details>` : ""}
    </div>`;

  if (tr && sinClave) html += `<div class="aviso">Conectá tu cuenta en Configuración para que ${nombreMotor()} arme el plan.</div>`;

  if (tr && p.formato === "recortes") {
    html += `<div class="tarjeta"><div class="paso ${p.candidatos.length ? "hecho" : ""}"><span class="num">2</span><b>Fragmentos candidatos</b>
      <span class="espacio"></span><button class="btn ${p.candidatos.length ? "" : "primario"}" data-acc="candidatos" ${ocupado || sinClave ? "disabled" : ""}>
      ${p.candidatos.length ? "Buscar de nuevo" : "Buscar fragmentos con ${nombreMotor()}"}</button></div>
      ${p.candidatos.length ? `<div style="margin-top:12px" id="cands">${p.candidatos.map((c, i) => `
        <label class="cand"><input type="checkbox" value="${i}">
          <div><b>${esc(c.titulo)}</b> <span class="sutil chico">${mmss(c.desde)} – ${mmss(c.hasta)}</span>
          <div class="chico">${esc(c.idea)}</div><div class="sutil chico">Gancho: “${esc(c.gancho)}”</div></div></label>`).join("")}
        <div class="fila fin"><button class="btn primario" data-acc="piezas" ${ocupado ? "disabled" : ""}>Armar los reels elegidos</button></div></div>` : ""}
    </div>`;
  } else if (tr && !p.piezas.length) {
    html += `<div class="tarjeta"><div class="paso"><span class="num">2</span><b>Plan de cortes</b><span class="espacio"></span>
      <button class="btn primario" data-acc="plan" ${ocupado || sinClave ? "disabled" : ""}>Armar el plan con ${nombreMotor()}</button></div>
      <p class="sutil chico">${nombreMotor()} elige el gancho, saca lo que no suma y cierra con el llamado a la acción.</p></div>`;
  }

  if (p.piezas.length) {
    if (p.piezas.length > 1)
      html += `<div class="tabs">${p.piezas.map((x) => `<div class="tab ${x.n === S.pieza ? "activo" : ""}" data-pieza="${x.n}">Reel ${x.n}${x.final ? " ✓" : ""}</div>`).join("")}</div>`;
    html += `<div id="pieza"></div>`;
  }
  html += `</div>`;
  $("#main").innerHTML = html;
  if (p.piezas.length) vistaPieza();
}

// ---------- editor de la pieza ----------

function textoEntre(s, e) {
  const ws = S.p.transcripcion?.palabras || [];
  return ws.filter((w) => s <= (w.s + w.e) / 2 && (w.s + w.e) / 2 <= e).map((w) => w.w).join(" ");
}

function vistaPieza() {
  const pz = piezaActual(), plan = S.plan, ia = pz.ia || {};
  if (!plan) return;
  const doble = plan.formato === "doble";
  const ocupado = corriendo();
  const sub = plan.subtitulos || (plan.subtitulos = {});
  const durEstimada = plan.cortes.reduce((a, c) => a + Math.max(0, c.hasta - c.desde), 0);
  const brollPend = (plan.broll || []).filter((b) => b.prompt && !b.imagen && !b.video).length;
  const v = Date.now();

  $("#pieza").innerHTML = `<div class="grid2">
  <div>
    <div class="tarjeta">
      <div class="paso hecho"><span class="num">2</span><b>Plan de cortes</b><span class="espacio"></span>
        <span class="sutil chico">≈ ${durEstimada.toFixed(0)} s antes de sacar silencios</span></div>
      ${ia.resumen ? `<p class="sutil chico">${esc(ia.resumen)}</p>` : ""}
      ${ia.advertencia ? `<div class="aviso">${esc(ia.advertencia)}</div>` : ""}
      <table style="margin-top:8px"><thead><tr><th>#</th><th>Nota</th><th>Desde</th><th>Hasta</th><th>Qué dice</th><th></th></tr></thead>
      <tbody>${plan.cortes.map((c, i) => `<tr>
        <td>${i + 1}</td>
        <td><input data-k="cortes.${i}.nota" value="${esc(c.nota)}" style="width:120px"></td>
        <td class="num"><input type="number" step="0.01" data-k="cortes.${i}.desde" value="${c.desde}"></td>
        <td class="num"><input type="number" step="0.01" data-k="cortes.${i}.hasta" value="${c.hasta}"></td>
        <td class="dice">${esc(textoEntre(c.desde, c.hasta)) || "<i>sin palabras</i>"}</td>
        <td class="acc"><button class="btn mini" data-mover="${i}:-1" ${i === 0 ? "disabled" : ""}>↑</button>
          <button class="btn mini" data-mover="${i}:1" ${i === plan.cortes.length - 1 ? "disabled" : ""}>↓</button>
          <button class="btn mini peligro" data-quitar="cortes:${i}">✕</button></td></tr>`).join("")}
      </tbody></table>
      <div class="fila" style="margin-top:8px"><button class="btn mini" data-agregar="cortes">+ Corte</button>
        <span class="sutil chico">Tiempos del video original, en segundos.</span></div>

      <h3>Textos en pantalla <span class="sutil chico" style="text-transform:none">(tiempos del video final)</span></h3>
      ${filas("textos", plan.textos, (t, i) => `
        <td><input data-k="textos.${i}.texto" value="${esc(t.texto)}"></td>
        <td style="width:110px"><select data-k="textos.${i}.posicion">
          <option value="arriba" ${t.posicion !== "centro" ? "selected" : ""}>Arriba</option>
          <option value="centro" ${t.posicion === "centro" ? "selected" : ""}>Centro</option></select></td>`)}
      <button class="btn mini" data-agregar="textos">+ Texto</button>

      ${doble ? `<h3>Gráficos (parte de arriba)</h3>
        ${S.p.imagenes.length ? `<div class="miniaturas" style="margin-bottom:8px">${S.p.imagenes.map((n) => `<img title="${esc(n)}" src="/api/proyectos/${S.p.id}/archivo/${encodeURIComponent(n)}">`).join("")}</div>` : ""}
        ${filas("graficos", plan.graficos, (g, i) => `
          <td><select data-k="graficos.${i}.imagen">${S.p.imagenes.map((n) => `<option ${n === g.imagen ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></td>`)}
        <div class="fila"><button class="btn mini" data-agregar="graficos" ${S.p.imagenes.length ? "" : "disabled"}>+ Gráfico</button>
          <label class="btn mini" style="margin:0;color:var(--texto)">Subir imágenes<input type="file" id="subir-imgs" accept="image/*" multiple hidden></label></div>` : ""}

      <h3>B-roll <span class="sutil chico" style="text-transform:none">(tiempos del video final · nunca en el gancho ni en el cierre)</span></h3>
      ${filas("broll", plan.broll, (b, i) => `
        <td>${b.imagen ? `<div class="fila"><img src="/api/proyectos/${S.p.id}/archivo/${encodeURIComponent(b.imagen)}?v=${v}" style="width:40px;height:60px;object-fit:cover;border-radius:4px">
          <span class="sutil chico">${esc(b.imagen)}</span><button class="btn mini" data-sinimg="${i}">Rehacer</button></div>`
          : `<input data-k="broll.${i}.prompt" value="${esc(b.prompt)}" placeholder="Escena en inglés, sin texto">`}</td>`)}
      <div class="fila"><button class="btn mini" data-agregar="broll">+ B-roll</button><span class="espacio"></span>
        ${brollPend ? `<select id="calidad" style="width:auto"><option value="low">Calidad baja</option><option value="medium" selected>Calidad media</option><option value="high">Calidad alta</option></select>
        <button class="btn" data-acc="broll" ${ocupado ? "disabled" : ""}>Generar ${brollPend} imagen${brollPend > 1 ? "es" : ""}</button>` : ""}</div>

      <h3>Pedirle cambios a ${nombreMotor()}</h3>
      <textarea id="indicaciones" placeholder="Ej: el gancho tiene que ser la parte de los 3 clientes; más corto, menos de 40 s"></textarea>
      <div class="fila fin" style="margin-top:8px"><button class="btn" data-acc="replan" ${ocupado ? "disabled" : ""}>Rehacer el plan</button></div>
    </div>

    <div class="tarjeta">
      <h2>Estilo</h2>
      <div class="fila" style="align-items:flex-start;gap:16px">
        <label class="check"><input type="checkbox" data-k="subtitulos.activar" ${sub.activar !== false ? "checked" : ""}> Subtítulos</label>
        <label>Color<input type="color" data-k="subtitulos.color" value="${sub.color || "#FFFFFF"}"></label>
        <label>Resaltado<input type="color" data-k="subtitulos.resaltado" value="${sub.resaltado || "#FFD400"}"></label>
        <label>Palabras por línea<select data-k="subtitulos.palabras_por_linea" data-num>
          ${[1, 2, 3, 4, 5].map((n) => `<option ${n === (sub.palabras_por_linea || 3) ? "selected" : ""}>${n}</option>`).join("")}</select></label>
        <label class="check" style="margin-top:22px"><input type="checkbox" data-k="subtitulos.mayusculas" ${sub.mayusculas ? "checked" : ""}> MAYÚSCULAS</label>
        <label>Ritmo<select data-k="recortar_silencios" data-num>
          <option value="0.45" ${plan.recortar_silencios == 0.45 ? "selected" : ""}>Dinámico</option>
          <option value="0.7" ${plan.recortar_silencios == 0.7 ? "selected" : ""}>Tranquilo</option>
          <option value="" ${plan.recortar_silencios == null ? "selected" : ""}>No tocar pausas</option></select></label>
      </div>
      <h3>Encuadre</h3>
      <div class="encuadre" id="encuadre"><img id="frame" src="/api/proyectos/${S.p.id}/frame?t=${Math.min(5, (S.p.duracion || 10) / 2)}"><div class="caja" id="caja"></div></div>
      <label id="barra-x" style="margin-top:10px" hidden>Horizontal
        <input type="range" min="0" max="1" step="0.01" data-k="encuadre_x" data-num value="${plan.encuadre_x ?? 0.5}"></label>
      <label id="barra-y" style="margin-top:10px" hidden>Vertical
        <input type="range" min="0" max="1" step="0.01" data-k="encuadre_y" data-num value="${plan.encuadre_y ?? 0.5}"></label>
      <p class="sutil chico">Mové la barra para que la cara quede dentro del recuadro amarillo: lo de afuera se recorta.</p>
    </div>
  </div>

  <div class="lateral-pieza">
    <div class="tarjeta">
      <div class="paso ${pz.borrador ? "hecho" : ""}"><span class="num">3</span><b>Borrador</b></div>
      <div style="margin-top:12px" class="visor ${pz.borrador ? "" : "vacio"}">
        ${pz.borrador ? `<video controls playsinline src="/api/proyectos/${S.p.id}/archivo/borrador-${pz.n}.mp4?v=${v}"></video>` : "Renderizá un borrador para revisar los cortes antes del final."}
      </div>
      <div class="fila" style="margin-top:12px">
        <button class="btn ${pz.borrador ? "" : "primario"} ancho" data-acc="borrador" ${ocupado ? "disabled" : ""}>${S.sucio ? "Guardar y renderizar borrador" : "Renderizar borrador"}</button>
        <button class="btn ghost ancho" data-acc="guardar" ${S.sucio ? "" : "disabled"}>Guardar cambios</button>
      </div>
    </div>
    <div class="tarjeta">
      <div class="paso ${pz.final ? "hecho" : ""}"><span class="num">4</span><b>Video final</b></div>
      <p class="sutil chico">1080×1920, volumen normalizado para redes.</p>
      <button class="btn ${pz.borrador && !pz.final ? "primario" : ""} ancho" data-acc="final" ${ocupado ? "disabled" : ""}>Renderizar final</button>
      ${pz.final ? `<div class="fila" style="margin-top:10px">
        <a class="btn primario ancho" style="text-align:center;text-decoration:none" href="/api/proyectos/${S.p.id}/archivo/final-${pz.n}.mp4?descargar=true">⬇ Descargar .mp4</a>
        <a class="btn ancho" style="text-align:center;text-decoration:none" href="/api/proyectos/${S.p.id}/archivo/final-${pz.n}.srt?descargar=true">⬇ Subtítulos .srt</a></div>` : ""}
    </div>
  </div></div>`;

  $("#frame").onload = dibujarCaja;
  $("#subir-imgs")?.addEventListener("change", subirImagenes);
}

function filas(clave, lista = [], celdas) {
  if (!lista.length) return `<p class="sutil chico">Ninguno.</p>`;
  return `<table><tbody>${lista.map((x, i) => `<tr>
    <td class="num"><input type="number" step="0.1" data-k="${clave}.${i}.desde" value="${x.desde}" title="Desde (s)"></td>
    <td class="num"><input type="number" step="0.1" data-k="${clave}.${i}.hasta" value="${x.hasta}" title="Hasta (s)"></td>
    ${celdas(x, i)}
    <td class="acc"><button class="btn mini peligro" data-quitar="${clave}:${i}">✕</button></td></tr>`).join("")}</tbody></table>`;
}

function dibujarCaja() {
  const img = $("#frame"), caja = $("#caja");
  if (!img || !img.naturalWidth) return;
  // El video se escala hasta cubrir el recuadro de salida y se recorta lo que sobra:
  // a los costados (video más ancho que la salida) o arriba y abajo (más alto).
  const salida = S.plan.formato === "doble" ? 1080 / 960 : 1080 / 1920;
  const fuente = img.naturalWidth / img.naturalHeight;
  const ancho = Math.min(1, salida / fuente), alto = Math.min(1, fuente / salida);
  const x = S.plan.encuadre_x ?? 0.5, y = S.plan.encuadre_y ?? 0.5;
  Object.assign(caja.style, {
    width: `${ancho * 100}%`, height: `${alto * 100}%`, bottom: "auto",
    left: `${x * (1 - ancho) * 100}%`, top: `${y * (1 - alto) * 100}%`,
  });
  $("#barra-x").hidden = ancho > 0.995;
  $("#barra-y").hidden = alto > 0.995;
}

function setRuta(obj, k, val) {
  const partes = k.split(".");
  let o = obj;
  for (const p of partes.slice(0, -1)) o = o[p] ?? (o[p] = {});
  o[partes.at(-1)] = val;
}
function marcarSucio() {
  if (S.sucio) return;
  S.sucio = true;
  const g = $('[data-acc="guardar"]'); if (g) g.disabled = false;
  const b = $('[data-acc="borrador"]'); if (b) b.textContent = "Guardar y renderizar borrador";
}

// edición en vivo sin redibujar (para no perder el foco)
$("#main").addEventListener("input", (e) => {
  const el = e.target, k = el.dataset.k;
  if (!k || !S.plan) return;
  let val = el.type === "checkbox" ? el.checked : el.value;
  if (el.type === "number" || el.dataset.num !== undefined) val = val === "" ? null : Number(val);
  setRuta(S.plan, k, val);
  marcarSucio();
  if (k === "encuadre_x" || k === "encuadre_y") dibujarCaja();
  if (/^cortes\.\d+\.(desde|hasta)$/.test(k)) {
    const i = +k.split(".")[1], c = S.plan.cortes[i];
    el.closest("tr").querySelector(".dice").textContent = textoEntre(c.desde, c.hasta);
  }
});

$("#main").addEventListener("click", async (e) => {
  const t = e.target.closest("button, .tab, .cand");
  if (!t) return;
  if (t.classList.contains("cand")) { setTimeout(() => t.classList.toggle("sel", t.querySelector("input").checked)); return; }
  if (t.dataset.pieza) {
    if (S.sucio && !confirm("Tenés cambios sin guardar. ¿Cambiar de reel igual?")) return;
    S.sucio = false; S.pieza = +t.dataset.pieza; S.plan = structuredClone(piezaActual().plan); vistaProyecto(); return;
  }
  const p = S.plan;
  if (t.dataset.mover) {
    const [i, d] = t.dataset.mover.split(":").map(Number);
    [p.cortes[i], p.cortes[i + d]] = [p.cortes[i + d], p.cortes[i]];
    marcarSucio(); return vistaPieza();
  }
  if (t.dataset.quitar) {
    const [k, i] = t.dataset.quitar.split(":");
    p[k].splice(+i, 1); marcarSucio(); return vistaPieza();
  }
  if (t.dataset.sinimg) { delete p.broll[+t.dataset.sinimg].imagen; marcarSucio(); return vistaPieza(); }
  if (t.dataset.agregar) {
    const k = t.dataset.agregar;
    p[k] = p[k] || [];
    const ult = p.cortes.at(-1);
    p[k].push({
      cortes: { desde: ult?.hasta ?? 0, hasta: (ult?.hasta ?? 0) + 5, nota: "" },
      textos: { desde: 0, hasta: 3, texto: "", posicion: "arriba" },
      graficos: { desde: 0, hasta: 5, imagen: S.p.imagenes[0] },
      broll: { desde: 5, hasta: 7.5, prompt: "" },
    }[k]);
    marcarSucio(); return vistaPieza();
  }
  const acc = t.dataset.acc;
  if (acc) accion(acc).catch(fallo);
});

async function guardar() {
  if (!S.sucio) return;
  const r = await api(`/api/proyectos/${S.p.id}/plan/${S.pieza}`, { method: "PUT", body: S.plan });
  S.sucio = false;
  return r;
}

async function accion(acc) {
  const id = S.p.id, n = S.pieza;
  const lanzar = async (url, body) => { await api(url, { method: "POST", body }); await abrir(id); };
  switch (acc) {
    case "transcribir": return lanzar(`/api/proyectos/${id}/transcribir`);
    case "candidatos": return lanzar(`/api/proyectos/${id}/candidatos`);
    case "plan": return lanzar(`/api/proyectos/${id}/plan`);
    case "piezas": {
      const idx = [...document.querySelectorAll("#cands input:checked")].map((x) => +x.value);
      if (!idx.length) return alert("Elegí al menos un fragmento.");
      return lanzar(`/api/proyectos/${id}/piezas`, { indices: idx });
    }
    case "replan": {
      const ind = $("#indicaciones").value.trim();
      if (S.sucio && !confirm("Rehacer el plan descarta los cambios manuales sin guardar. ¿Seguir?")) return;
      S.sucio = false;
      return lanzar(`/api/proyectos/${id}/plan/${n}`, { indicaciones: ind });
    }
    case "guardar": {
      const r = await guardar();
      if (r) alert(`Guardado. Duración final estimada: ${r.duracion} s`);
      return abrir(id);
    }
    case "broll": {
      const cant = S.plan.broll.filter((b) => b.prompt && !b.imagen && !b.video).length;
      if (!confirm(`Se van a generar ${cant} imagen(es) con tu clave de OpenAI o Gemini. Cada una tiene costo. ¿Seguir?`)) return;
      await guardar();
      return lanzar(`/api/proyectos/${id}/broll/${n}?calidad=${$("#calidad").value}`);
    }
    case "borrador":
    case "final":
      await guardar();
      return lanzar(`/api/proyectos/${id}/render/${n}?borrador=${acc === "borrador"}`);
    case "borrar":
      if (!confirm("¿Borrar este proyecto y todos sus renders? El video original de tu compu no se toca.")) return;
      await api(`/api/proyectos/${id}`, { method: "DELETE" });
      S.sucio = false; location.hash = "";
  }
}

async function subirImagenes(e) {
  const fd = new FormData();
  for (const f of e.target.files) fd.append("imagenes", f);
  try {
    await api(`/api/proyectos/${S.p.id}/imagenes`, { method: "POST", body: fd });
    const d = await api(`/api/proyectos/${S.p.id}`);
    S.p.imagenes = d.imagenes;
    vistaPieza();
  } catch (err) { fallo(err); }
}

// ---------- configuración ----------

// Listo para armar planes con el motor elegido (Claude o GPT)
const conectado = () => {
  const c = S.cfg;
  if (!c) return false;
  return c.motor === "gpt" ? !!(c.chatgpt?.conectado && c.modelo) : !!c.anthropic?.conectado;
};
const nombreMotor = () => (S.cfg?.motor === "gpt" ? "GPT" : "Claude");

async function cargarConfig(forzar = false) { S.cfg = await api(`/api/config${forzar ? "?forzar=true" : ""}`); }

function pintarConfig() {
  const c = S.cfg, a = c.anthropic, g = c.chatgpt;
  $("#cfg-estado").innerHTML = [
    ["ffmpeg", c.ffmpeg], ["Subtítulos (libass)", c.libass], ["Modelo de transcripción", c.modelo_descargado],
    ["OpenAI (b-roll)", c.claves.OPENAI_API_KEY], ["Gemini (b-roll)", c.claves.GEMINI_API_KEY],
  ].map(([n, ok]) => `<span class="punto ${ok ? "si" : "no"}">${n}</span>`).join("");

  $("#cfg-motor").innerHTML = [
    ["claude", "Claude", "Con tu cuenta de Anthropic Console (pago por uso)."],
    ["gpt", "GPT", "Con tu plan de ChatGPT Plus o Pro, sin costo extra."],
  ].map(([k, t, d]) => `<div class="formato ${c.motor === k ? "sel" : ""}" data-motor="${k}"><b>${t}</b><span class="sutil chico">${d}</span></div>`).join("");
  document.querySelectorAll("[data-motor]").forEach((el) => (el.onclick = async () => {
    S.cfg = await api("/api/ajustes", { method: "POST", body: { motor: el.dataset.motor } });
    pintarConfig();
  }));
  $("#cfg-avanzado").hidden = c.motor === "gpt";

  let html = "";
  if (c.motor === "gpt") {
    if (g.conectado) {
      html = `<div class="fila"><span class="punto si">Conectado como ${esc(g.email || "tu cuenta de ChatGPT")}</span><span class="espacio"></span>
        <button type="button" class="btn mini" id="cfg-gpt-salir">Desconectar</button></div>
        <label style="margin-top:12px">Modelo <select id="cfg-modelo"><option>${esc(c.modelo || "Cargando…")}</option></select></label>`;
    } else {
      html = `<p class="sutil chico">Iniciá sesión con tu cuenta de ChatGPT y aceptá usar tu plan en esta app. El uso cuenta
        dentro de los límites de tu plan.</p>
        <button type="button" class="btn chatgpt" id="cfg-gpt-login">Continue with ChatGPT</button>
        ${S.esperandoLogin ? `<span class="sutil chico"><span class="spin"></span>Esperando que termines en la otra pestaña…</span>` : ""}`;
    }
    html += `<p class="sutil chico">Con el plan de ChatGPT no se pueden generar imágenes: para el b-roll hace falta una clave de API.</p>`;
  } else if (a.conectado) {
    html = `<div class="fila"><span class="punto si">Conectado ${a.modo === "clave" ? "con clave de API" : "con tu cuenta"}</span><span class="espacio"></span>
      ${a.modo === "clave" ? `<button type="button" class="btn mini" id="cfg-quitar">Quitar clave</button>`
                           : `<button type="button" class="btn mini" id="cfg-salir">Cerrar sesión</button>`}</div>`;
  } else if (a.ant) {
    html = `<p class="sutil chico">Iniciá sesión con tu cuenta de Anthropic Console: se abre una Terminal y el navegador, elegís
      la organización y listo. El uso se cobra a esa cuenta.</p>
      <button type="button" class="btn primario" id="cfg-login">Iniciar sesión con Anthropic</button>
      ${S.esperandoLogin ? `<span class="sutil chico"><span class="spin"></span>Esperando que termines en el navegador…</span>` : ""}`;
  } else {
    html = `<p class="sutil chico">Para iniciar sesión sin pegar claves, instalá la herramienta oficial <code>ant</code> en una terminal:</p>
      <pre class="cmd">brew install anthropics/tap/ant</pre>
      <button type="button" class="btn mini" id="cfg-revisar">Ya la instalé</button>`;
  }
  if (c.motor !== "gpt") {
    if (a.detalle) html += `<p class="chico" style="color:var(--error)">${esc(a.detalle)}</p>`;
    html += `<p class="sutil chico">La suscripción de claude.ai (Pro/Max) no se puede usar en apps de terceros; hace falta una cuenta de Anthropic Console.</p>`;
  }
  $("#cfg-cuenta").innerHTML = html;

  $("#cfg-login")?.addEventListener("click", login);
  $("#cfg-gpt-login")?.addEventListener("click", loginChatGPT);
  $("#cfg-revisar")?.addEventListener("click", async () => { await cargarConfig(true); pintarConfig(); });
  $("#cfg-salir")?.addEventListener("click", async () => { S.cfg = await api("/api/sesion/cerrar", { method: "POST" }); pintarConfig(); });
  $("#cfg-gpt-salir")?.addEventListener("click", async () => { S.cfg = await api("/api/chatgpt/cerrar", { method: "POST" }); pintarConfig(); });
  $("#cfg-quitar")?.addEventListener("click", async () => {
    S.cfg = await api("/api/config", { method: "POST", body: { claves: { ANTHROPIC_API_KEY: null } } }); pintarConfig();
  });
  if ($("#cfg-modelo")) cargarModelos();
}

async function cargarModelos() {
  const sel = $("#cfg-modelo");
  try {
    const lista = await api("/api/chatgpt/modelos");
    sel.innerHTML = lista.map((m) => `<option value="${esc(m.slug)}" ${m.slug === S.cfg.modelo ? "selected" : ""}>${esc(m.nombre)}</option>`).join("");
    if (!lista.some((m) => m.slug === S.cfg.modelo) && lista[0]) {
      S.cfg = await api("/api/ajustes", { method: "POST", body: { modelo_gpt: lista[0].slug } });
    }
    sel.onchange = async () => { S.cfg = await api("/api/ajustes", { method: "POST", body: { modelo_gpt: sel.value } }); };
  } catch (e) { sel.innerHTML = `<option>${esc(e.message)}</option>`; }
}

async function esperarConexion() {
  S.esperandoLogin = true; pintarConfig();
  for (let i = 0; i < 100 && S.esperandoLogin; i++) {   // ~5 minutos
    await new Promise((r) => setTimeout(r, 3000));
    await cargarConfig(true).catch(() => {});
    if (conectado()) break;
  }
  S.esperandoLogin = false; pintarConfig();
  if (conectado()) ruta();
}
async function login() {
  try { await api("/api/sesion/iniciar", { method: "POST" }); } catch (e) { return fallo(e); }
  esperarConexion();
}
function loginChatGPT() {
  window.open("/api/chatgpt/login", "_blank");
  esperarConexion();
}
async function abrirConfig() { await cargarConfig(true); pintarConfig(); $("#dlg-config").showModal(); }
$("#btn-config").onclick = abrirConfig;
$("#dlg-config").addEventListener("close", () => (S.esperandoLogin = false));
$("#cfg-guardar").onclick = async (e) => {
  e.preventDefault();
  const claves = {};
  document.querySelectorAll("#dlg-config input").forEach((i) => { if (i.value.trim()) claves[i.name] = i.value; i.value = ""; });
  try { S.cfg = await api("/api/config", { method: "POST", body: { claves } }); pintarConfig(); }
  catch (err) { return fallo(err); }
  if (claves.ANTHROPIC_API_KEY && !S.cfg.anthropic.conectado) return alert("Esa clave de Anthropic no funcionó.");
  $("#dlg-config").close();
  ruta();
};

window.addEventListener("beforeunload", (e) => { if (S.sucio) e.preventDefault(); });

(async () => {
  await cargarConfig().catch(() => {});
  ruta();
})();
