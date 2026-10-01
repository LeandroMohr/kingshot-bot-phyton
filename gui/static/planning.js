"use strict";

// Planning panels (Account, Troops, Events, Resources). Data: memory/planning/<account>.json
// served by /api/planning as { snapshot, formations }. Uses el/api/toast from app.js, tr from i18n.js.
const Planning = (() => {
  const CLASSES = ["infantry", "cavalry", "archer"];
  const classLabel = (cls) => tr(`class.${cls}`);
  const classShort = (cls) => tr(`classShort.${cls}`);
  const GEAR_SLOTS = ["helmet", "gloves", "armor", "boots"];
  const slotLabel = (slot) => tr(`gear.${slot}`);
  const RARITY_OPTIONS = [
    { rarity: "Grey", label: "Common" },
    { rarity: "Green", label: "Uncommon" },
    { rarity: "Blue", label: "Rare" },
    { rarity: "Purple", label: "Epic" },
    { rarity: "Gold", label: "Mythic" },
  ];
  // Shards for each of the 6 parts of a star level (knowledge/heroes.json, checked 2026-09-24).
  const STAR_TIER_COSTS = {
    1: [1, 1, 2, 2, 2, 2],
    2: [5, 5, 5, 5, 5, 15],
    3: [15, 15, 15, 15, 15, 40],
    4: [40, 40, 40, 40, 40, 100],
    5: [100, 100, 100, 100, 100, 100],
  };
  const INV = ["additional_inventory"];
  // [label key, path in the snapshot, label params]
  const RESOURCE_GROUPS = [
    { title: "res.general", items: [
      ["res.bread", [...INV, "resource_totals", "bread"]],
      ["res.wood", [...INV, "resource_totals", "wood"]],
      ["res.stone", [...INV, "resource_totals", "stone"]],
      ["res.iron", [...INV, "resource_totals", "iron"]],
      ["res.gold", [...INV, "resource_totals", "gold"]],
      ["res.gems", [...INV, "resource_totals", "gems"]],
      ["res.stamina", [...INV, "resource_totals", "governor_stamina"]],
      ["res.petFood", [...INV, "resource_totals", "pet_food"]],
    ] },
    { title: "res.govGear", items: [
      ["res.satin", ["governor_gear", "materials", "satin"]],
      ["res.threads", ["governor_gear", "materials", "gilded_threads"]],
      ["res.vision", ["governor_gear", "materials", "artisans_vision"]],
    ] },
    { title: "res.govCharm", items: [
      ["res.charmGuides", ["governor_charms", "materials", "charm_guides"]],
      ["res.charmDesigns", ["governor_charms", "materials", "charm_designs"]],
    ] },
    { title: "res.skillbooks", items: [
      ["res.conquestMythic", [...INV, "hero_progression_items", "skillbooks", "conquest", "mythic"]],
      ["res.conquestEpic", [...INV, "hero_progression_items", "skillbooks", "conquest", "epic"]],
      ["res.conquestRare", [...INV, "hero_progression_items", "skillbooks", "conquest", "rare"]],
      ["res.expeditionMythic", [...INV, "hero_progression_items", "skillbooks", "expedition", "mythic"]],
      ["res.expeditionEpic", [...INV, "hero_progression_items", "skillbooks", "expedition", "epic"]],
      ["res.expeditionRare", [...INV, "hero_progression_items", "skillbooks", "expedition", "rare"]],
    ] },
    { title: "res.keys", items: [
      ["res.silver", [...INV, "hero_recruitment_keys", "silver"]],
      ["res.gold", [...INV, "hero_recruitment_keys", "gold"]],
    ] },
    { title: "res.widgetChests", items: [
      ["res.generation", [...INV, "widget_chests_by_generation", "generation_4"], { gen: 4 }],
      ["res.generation", [...INV, "widget_chests_by_generation", "generation_3"], { gen: 3 }],
      ["res.generation", [...INV, "widget_chests_by_generation", "generation_1"], { gen: 1 }],
    ] },
  ];

  let cache = { accountId: null, promise: null, doc: null };
  let mounted = [];
  let pending = null;
  let saveTimer = null;
  const openHeroes = new Set();
  const tracking = {};  // consumption tracker rows (browser only, not saved)

  // -- data -------------------------------------------------------------------
  const snap = () => cache.doc.snapshot;
  const forms = () => cache.doc.formations;
  const heroes = () => snap().heroes || [];
  const heroById = (id) => heroes().find((h) => h.id === id);
  const heroName = (id) => (heroById(id) || {}).name || id;
  const heroesByClass = (cls) => heroes().filter((h) => (h.class || "").toLowerCase() === cls);
  const marchQueues = () => forms().rules.march_queues.unlocked ?? 6;
  const stock = () => forms().troop_inventory_snapshot;

  function getPath(obj, path) { return path.reduce((o, k) => (o == null ? o : o[k]), obj); }
  function setPath(obj, path, value) {
    let cur = obj;
    for (const key of path.slice(0, -1)) cur = cur[key] ??= {};
    cur[path[path.length - 1]] = value;
  }
  function numOrNull(v) {
    if (v === "" || v == null) return null;
    const n = Number(v);
    return Number.isNaN(n) ? null : n;
  }
  const round1 = (n) => Math.round(n * 10) / 10;
  const fmt = (n) => (n ?? 0).toLocaleString();

  // Fill the structure the panels expect; older files keep one shared split per event.
  function normalize(doc) {
    const s = doc.snapshot;
    const f = doc.formations;
    s.account ??= {};
    s.account.governor ??= {};
    s.account.kingdom ??= {};
    s.account.power ??= {};
    s.heroes ??= [];
    f.rules ??= {};
    f.rules.march_queues ??= { unlocked: 6 };
    f.troop_inventory_snapshot ??= {};
    for (const cls of CLASSES) f.troop_inventory_snapshot[cls] ??= { total: 0 };
    f.events ??= {};

    const ensureRow = (row, split, cap) => {
      row.troop_split_percent ??= { ...(split || { infantry: 0, cavalry: 0, archer: 0 }) };
      row.troops ??= Object.fromEntries(CLASSES.map((c) => [c, Math.round(cap * (row.troop_split_percent[c] || 0) / 100)]));
    };
    const ev = f.events;
    if (ev.kings_castle) {
      ev.kings_castle.troop_cap ??= 147000;
      for (const key of ["rally_lead", "joiner"]) {
        if (ev.kings_castle[key]) ensureRow(ev.kings_castle[key], ev.kings_castle[key].troop_split_percent, ev.kings_castle.troop_cap);
      }
    }
    for (const key of ["swordland_showdown", "tri_alliance_clash"]) {
      if (!ev[key]) continue;
      ev[key].troop_cap ??= 147000;
      ev[key].teams.forEach((t) => ensureRow(t, ev[key].troop_split_percent, ev[key].troop_cap));
    }
    if (ev.bear_hunt) {
      const bh = ev.bear_hunt;
      bh.troop_cap ??= bh.kingdom_troop_cap_per_group || 100000;
      bh.teams.forEach((t) => {
        t.troops ??= { infantry: 0, cavalry: 0, archer: 0 };
        t.troop_split_percent ??= Object.fromEntries(CLASSES.map((c) => [c, round1((t.troops[c] || 0) / bh.troop_cap * 100)]));
      });
    }
    return doc;
  }

  // -- loading / saving ---------------------------------------------------------
  function fetchDoc(accountId) {
    if (cache.accountId !== accountId) {
      flushSave();
      const entry = { accountId, doc: null, promise: null };
      entry.promise = api(`/api/planning?account_id=${encodeURIComponent(accountId)}`).then(({ planning }) => {
        entry.doc = planning ? normalize(planning) : null;
      });
      cache = entry;
    }
    return cache.promise;
  }

  function scheduleSave() {
    pending = { accountId: cache.accountId, doc: cache.doc };
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flushSave, 600);
  }

  async function flushSave() {
    clearTimeout(saveTimer);
    if (!pending) return;
    const { accountId, doc } = pending;
    pending = null;
    try {
      await api("/api/planning", { account_id: accountId, planning: doc });
      toast(tr("saved"));
    } catch (err) {
      toast(err.message, true);
    }
  }

  function edited(redraw = false) {
    scheduleSave();
    if (redraw) redrawAll();
  }

  function redrawAll() {
    mounted = mounted.filter((m) => m.container.isConnected);
    mounted.forEach((m) => m.draw());
  }

  async function mount(panelId, container, accountId) {
    try {
      await fetchDoc(accountId);
    } catch (err) {
      container.replaceChildren(el("p", { class: "muted" }, err.message));
      return;
    }
    if (cache.accountId !== accountId || !container.isConnected) return;
    const draw = () => container.replaceChildren(...(cache.doc
      ? PANELS[panelId]()
      : [el("p", { class: "muted" }, tr("plan.none"))]));
    mounted = mounted.filter((m) => m.container.isConnected);
    mounted.push({ container, draw });
    draw();
  }

  // -- small controls -----------------------------------------------------------
  function field(label, control, extraClass = "") {
    return el("label", { class: `field ${extraClass}` }, [el("span", {}, label), control]);
  }

  function numInput(value, onChange, attrs = {}) {
    return el("input", {
      type: "number", value: value ?? "", ...attrs,
      onchange: (e) => onChange(numOrNull(e.target.value)),
    });
  }

  function textInput(value, onChange) {
    return el("input", { type: "text", value: value ?? "", onchange: (e) => onChange(e.target.value) });
  }

  function selectInput(options, current, onChange) {
    return el("select", { onchange: (e) => onChange(e.target.value) },
      options.map(([value, label, disabled]) => el("option", {
        value, selected: String(value) === String(current ?? ""), disabled: !!disabled,
      }, label)));
  }

  function classTag(cls) {
    return el("span", { class: `badge class-${cls}` }, classShort(cls));
  }

  function details(title, children, open = false) {
    return el("details", { class: "howto", open }, [el("summary", {}, title), el("div", { class: "howto-body" }, children)]);
  }

  // -- Account: profile ------------------------------------------------------------
  function panelProfile() {
    const acc = snap().account;
    return [el("div", { class: "task-fields" }, [
      field(tr("profile.governor"), textInput(acc.governor.name, (v) => { acc.governor.name = v; edited(); })),
      field(tr("profile.vip"), numInput(acc.governor.vip_level, (v) => { acc.governor.vip_level = v; edited(); }, { min: 0, max: 12 })),
      field(tr("profile.kingdom"), numInput(acc.kingdom.current, (v) => { acc.kingdom.current = v; edited(); }, { min: 1 })),
      field(tr("profile.power"), numInput(acc.power.value, (v) => { acc.power.value = v; edited(); }, { min: 0, class: "wide" })),
      field(tr("profile.queues"), selectInput([1, 2, 3, 4, 5, 6].map((n) => [n, String(n)]), marchQueues(), (v) => {
        forms().rules.march_queues.unlocked = Number(v);
        edited(true);
      })),
    ])];
  }

  // -- Account: heroes ---------------------------------------------------------------
  function shardCount(hero) {
    return getPath(snap(), [...INV, "hero_progression_items", "hero_specific_shards", hero.id]) ?? null;
  }

  function shardsToNextSegment(hero) {
    const stars = hero.stars ?? 0;
    const done = hero.star_progress?.segments_completed ?? 0;
    const costs = STAR_TIER_COSTS[stars + 1];
    return stars >= 5 || !costs || done >= 6 ? 0 : costs[done];
  }

  function shardsToMaxStars(hero) {
    const stars = hero.stars ?? 0;
    const done = hero.star_progress?.segments_completed ?? 0;
    let total = 0;
    for (let star = stars + 1; star <= 5; star++) {
      STAR_TIER_COSTS[star].forEach((cost, i) => { if (star > stars + 1 || i >= done) total += cost; });
    }
    return total;
  }

  function panelHeroes() {
    const setAll = (open) => {
      heroes().forEach((h) => (open ? openHeroes.add(h.id) : openHeroes.delete(h.id)));
      redrawAll();
    };
    if (!heroes().length) return [el("p", { class: "muted" }, tr("heroes.none"))];
    return [
      el("div", { class: "inline" }, [
        el("button", { class: "ghost", onclick: () => setAll(true) }, tr("heroes.expandAll")),
        el("button", { class: "ghost", onclick: () => setAll(false) }, tr("heroes.collapseAll")),
      ]),
      el("div", { class: "hero-list" }, heroes().map(heroCard)),
    ];
  }

  function heroCard(hero) {
    const cls = (hero.class || "").toLowerCase();
    hero.skills ??= {};
    hero.gear ??= {};
    const card = el("details", { class: "hero-card", open: openHeroes.has(hero.id) }, [
      el("summary", {}, [
        el("strong", {}, hero.name),
        classTag(cls),
        el("span", { class: "badge" }, `${hero.rarity ?? "?"} · Gen ${hero.generation ?? "?"}`),
        el("span", { class: "badge" }, `${hero.stars ?? "?"}★`),
      ]),
      el("div", { class: "hero-body" }, [
        el("h4", {}, tr("heroes.progress")),
        el("div", { class: "task-fields" }, [
          field(tr("heroes.level"), numInput(hero.level, (v) => { hero.level = v; edited(); }, { min: 1, max: 80 })),
          field(tr("heroes.stars"), numInput(hero.stars, (v) => { hero.stars = v; edited(true); }, { min: 0, max: 5 })),
          field(tr("heroes.skillLevel"), numInput(hero.skills.all_skills_level, (v) => { hero.skills.all_skills_level = v; edited(); }, { min: 1, max: 5 })),
          field(tr("heroes.skillStatus"), selectInput([["maxed", tr("heroes.skillMaxed")], ["in_progress", tr("heroes.skillInProgress")]], hero.skills.status,
            (v) => { hero.skills.status = v; edited(); })),
        ]),
        el("h4", {}, tr("heroes.starsShards")),
        shardsBlock(hero),
        el("h4", {}, tr("heroes.gear")),
        el("div", { class: "gear-grid" }, GEAR_SLOTS.map((slot) => gearSlot(hero, slot))),
        hero.exclusive_gear ? el("h4", {}, tr("heroes.exclusive")) : null,
        hero.exclusive_gear ? el("div", { class: "task-fields" }, [
          el("span", {}, hero.exclusive_gear.name),
          field(tr("heroes.widgetLevel"), numInput(hero.exclusive_gear.widget_level ?? 0,
            (v) => { hero.exclusive_gear.widget_level = v; edited(); }, { min: 0, max: 10 })),
        ]) : null,
      ]),
    ]);
    card.addEventListener("toggle", () => (card.open ? openHeroes.add(hero.id) : openHeroes.delete(hero.id)));
    return card;
  }

  function shardsBlock(hero) {
    const stars = hero.stars ?? 0;
    const done = hero.star_progress?.segments_completed ?? 0;
    const track = el("div", { class: "star-track" }, [1, 2, 3, 4, 5].map((i) => {
      const state = i <= stars ? "filled" : i === stars + 1 ? "current" : "locked";
      return el("div", { class: `star-slot ${state}` }, [
        el("span", {}, "★"),
        i === stars + 1 && stars < 5 ? el("div", { class: "segments" }, STAR_TIER_COSTS[i].map((cost, idx) =>
          el("span", { class: `seg ${idx < done ? "filled" : ""}`, title: tr("heroes.segmentTitle", { index: idx + 1, cost }) }))) : null,
      ]);
    }));
    const info = stars >= 5
      ? tr("heroes.maxStars")
      : tr("heroes.shardsMissing", { next: shardsToNextSegment(hero), total: shardsToMaxStars(hero) });
    return el("div", { class: "shards" }, [
      track,
      el("div", { class: "task-fields" }, [
        field(tr("heroes.shardsStock"), numInput(shardCount(hero), (v) => {
          setPath(snap(), [...INV, "hero_progression_items", "hero_specific_shards", hero.id], v);
          edited();
        }, { min: 0 })),
        field(tr("heroes.segmentsDone"), numInput(done, (v) => {
          hero.star_progress ??= { segments_required: 6, target_stars: stars + 1 };
          hero.star_progress.segments_completed = Math.max(0, Math.min(6, v ?? 0));
          edited(true);
        }, { min: 0, max: 6 })),
      ]),
      el("p", { class: "muted small" }, info),
    ]);
  }

  function gearSlot(hero, slot) {
    const gear = hero.gear[slot] ??= {};
    const box = el("div", { class: "gear-slot" }, [
      el("strong", {}, slotLabel(slot)),
      selectInput([["", tr("gear.none")], ...RARITY_OPTIONS.map((r) => [r.rarity, r.label])], gear.rarity, (v) => {
        const opt = RARITY_OPTIONS.find((r) => r.rarity === v);
        gear.rarity = opt ? opt.rarity : null;
        gear.rarity_label = opt ? opt.label : null;
        edited();
      }),
      el("div", { class: "inline" }, [
        field(tr("heroes.level"), numInput(gear.level, (v) => { gear.level = v; edited(); }, { min: 0 })),
        field(tr("gear.mastery"), numInput(gear.mastery, (v) => { gear.mastery = v; edited(); }, { min: 0, max: 20 })),
      ]),
    ]);
    box.append(el("button", { class: "ghost small-btn", onclick: () => toggleMovePicker(box, hero, slot) }, tr("gear.move")));
    return box;
  }

  function gearText(gear) {
    if (gear.level == null) return gear.rarity_label || gear.rarity || tr("gear.undeveloped");
    return tr("gear.describe", { rarity: gear.rarity_label || gear.rarity || "?", level: gear.level, mastery: gear.mastery ?? 0 });
  }

  function toggleMovePicker(box, source, slot) {
    const existing = box.querySelector(".move-picker");
    if (existing) { existing.remove(); return; }
    const targets = heroes().filter((h) => h.class === source.class && h.id !== source.id);
    if (!targets.length) { toast(tr("gear.noTarget", { cls: source.class }), true); return; }
    const select = selectInput(targets.map((h) => [h.id, h.name]), targets[0].id, () => {});
    const picker = el("div", { class: "move-picker inline" }, [
      select,
      el("button", { onclick: () => moveGear(source, slot, heroById(select.value)) }, tr("gear.confirm")),
      el("button", { class: "ghost", onclick: () => picker.remove() }, tr("gear.cancel")),
    ]);
    box.append(picker);
  }

  function moveGear(source, slot, target) {
    const from = source.gear[slot] || {};
    const to = target.gear[slot] || {};
    let msg = tr("gear.moveConfirm", { source: source.name, from: gearText(from), target: target.name, slot: slotLabel(slot) });
    if (to.level != null) msg += tr("gear.moveReplace", { target: target.name, to: gearText(to) });
    if (!confirm(msg + tr("gear.moveQuestion"))) return;
    target.gear ??= {};
    target.gear[slot] = { ...from };
    source.gear[slot] = { rarity: null, rarity_label: tr("gear.unequipped"), level: null, mastery: null };
    edited(true);
  }

  // -- Account: hero plan (read-only) ----------------------------------------------
  function panelHeroPlan() {
    const f = forms();
    const out = [];
    const ranking = f.hero_rankings;
    if (ranking) {
      out.push(el("h4", {}, tr("plan.ranking")));
      out.push(el("div", { class: "rank-grid" }, CLASSES.map((cls) => el("div", {}, [
        el("strong", {}, classLabel(cls)),
        el("ol", {}, (ranking[cls] || []).map((id) => el("li", {}, heroName(id)))),
      ]))));
      if (ranking.not_recommended_for_combat?.length) {
        out.push(el("div", { class: "callout warn" }, [el("strong", {}, tr("plan.notRecommended")),
          ranking.not_recommended_for_combat.join("; ")]));
      }
      if (ranking.note) out.push(el("p", { class: "muted small" }, ranking.note));
    }
    if (f.gear_transition_process?.steps) {
      out.push(details(tr("plan.gearTransition"),
        [el("ol", {}, f.gear_transition_process.steps.map((s) => el("li", {}, s.replace(/^\d+\)\s*/, ""))))]));
    }
    const roadmap = f.hero_generation_roadmap;
    if (roadmap) {
      const gens = (roadmap.timeline || []).map((g) => details(
        tr("plan.generation", {
          gen: g.generation,
          hero: heroName(g.primary_investment),
          alt: g.alternative ? tr("plan.or", { hero: heroName(g.alternative) }) : "",
          status: g.status,
        }),
        [
          el("p", {}, [el("strong", {}, tr("plan.target")), g.target]),
          g.reason && el("p", {}, g.reason),
          g.skip?.length ? el("p", {}, [el("strong", {}, tr("plan.skip")), g.skip.map(heroName).join(", ")]) : null,
          g.secondary_free_track ? el("p", {}, [el("strong", {}, tr("plan.freeTrack", { hero: heroName(g.secondary_free_track.hero) })), g.secondary_free_track.note]) : null,
          g.gear_transition ? el("p", {}, [el("strong", {}, tr("plan.gearSwap", { when: g.gear_transition.when })), g.gear_transition.action]) : null,
          g.shard_source ? el("p", { class: "muted small" }, g.shard_source) : null,
          g.bonus_note ? el("p", { class: "muted small" }, g.bonus_note) : null,
        ],
        g.status === "current",
      ));
      out.push(el("h4", {}, tr("plan.roadmap")));
      if (roadmap.big_investment_cadence) out.push(el("p", {}, roadmap.big_investment_cadence));
      if (roadmap.note) out.push(el("p", { class: "muted small" }, roadmap.note));
      out.push(...gens);
    }
    return out.length ? out : [el("p", { class: "muted" }, tr("plan.noHeroPlan"))];
  }

  // -- Resources: stock --------------------------------------------------------------
  function panelResourceStock() {
    return RESOURCE_GROUPS.map((group) => el("div", { class: "resource-group" }, [
      el("h4", {}, tr(group.title)),
      el("table", { class: "data-table" }, [
        el("thead", {}, el("tr", {}, [el("th", {}, tr("res.item")), el("th", {}, tr("res.current")), el("th", {}, "")])),
        el("tbody", {}, group.items.flatMap(([labelKey, path, params]) => {
          const label = tr(labelKey, params);
          const key = path.join(".");
          const value = getPath(snap(), path);
          const rows = [el("tr", {}, [
            el("td", {}, label),
            el("td", {}, numInput(value, (v) => { setPath(snap(), path, v ?? 0); edited(true); }, { min: 0, class: "wide" })),
            el("td", {}, el("button", {
              class: "ghost",
              onclick: () => { if (tracking[key]) delete tracking[key]; else tracking[key] = { days: [] }; redrawAll(); },
            }, tracking[key] ? tr("res.untrack") : tr("res.track"))),
          ])];
          if (tracking[key]) rows.push(el("tr", {}, el("td", { colspan: 3 }, dayTracker(label, value ?? 0, tracking[key]))));
          return rows;
        })),
      ]),
    ]));
  }

  function dayTracker(label, start, tracker) {
    let balance = start;
    let used = 0;
    const rows = tracker.days.map((day, i) => {
      balance -= day.used || 0;
      used += day.used || 0;
      const avg = used / (i + 1);
      const left = avg > 0 ? balance / avg : Infinity;
      return el("tr", {}, [
        el("td", {}, tr("res.day", { n: i + 1 })),
        el("td", {}, numInput(day.used, (v) => { day.used = v || 0; redrawAll(); }, { min: 0, class: "wide" })),
        el("td", { class: balance < 0 ? "negative" : "positive" }, fmt(Math.round(balance))),
        el("td", {}, fmt(Math.round(avg))),
        el("td", {}, Number.isFinite(left) ? left.toFixed(1) : "—"),
      ]);
    });
    return el("div", { class: "day-tracker" }, [
      el("button", { class: "ghost", onclick: () => { tracker.days.push({ used: 0 }); redrawAll(); } }, tr("res.addDay", { label })),
      el("table", { class: "data-table" }, [
        el("thead", {}, el("tr", {}, ["res.dayCol", "res.spent", "res.balance", "res.average", "res.daysLeft"].map((k) => el("th", {}, tr(k))))),
        el("tbody", {}, rows),
      ]),
    ]);
  }

  // -- Troops: stock and plan ----------------------------------------------------------
  function panelTroopStock() {
    const inv = stock();
    const levelKeys = (data) => Object.keys(data).filter((k) => !["total"].includes(k));
    return [
      el("div", { class: "troop-grid" }, CLASSES.map((cls) => {
        const data = inv[cls];
        return el("div", { class: "troop-card" }, [
          el("h4", {}, classLabel(cls)),
          ...levelKeys(data).map((key) => field(key.startsWith("level_") ? tr("troops.level", { n: key.slice(6) }) : key, numInput(data[key], (v) => {
            data[key] = v || 0;
            data.total = levelKeys(data).reduce((sum, k) => sum + (data[k] || 0), 0);
            inv.date = new Date().toISOString().slice(0, 10);
            edited(true);
          }, { min: 0, class: "wide" }), "row")),
          el("div", { class: "troop-total" }, [tr("troops.total"), el("strong", {}, fmt(data.total))]),
        ]);
      })),
      el("p", { class: "muted small" }, [inv.date ? tr("troops.updated", { date: inv.date }) : "", inv.note || ""]),
    ];
  }

  function panelTroopPlan() {
    const plan = forms().troop_development_plan;
    if (!plan) return [el("p", { class: "muted" }, tr("troops.noPlan"))];
    const ratio = plan.usage_weighted_target_ratio || {};
    const out = [];
    if (ratio.approx_ratio) out.push(el("p", {}, [el("strong", {}, tr("troops.ratio")), ratio.approx_ratio]));
    if (ratio.guidance) out.push(el("p", {}, ratio.guidance));
    out.push(el("table", { class: "data-table" }, [
      el("thead", {}, el("tr", {}, ["troops.priority", "troops.type", "troops.current", "troops.target", "troops.missing", "troops.reason"].map((k) => el("th", {}, tr(k))))),
      el("tbody", {}, [...(plan.milestones || [])].sort((a, b) => (a.priority ?? 9) - (b.priority ?? 9)).map((m) => {
        const current = stock()[m.troop_type]?.total ?? 0;
        const gap = Math.max(0, (m.target_total || 0) - current);
        return el("tr", {}, [
          el("td", {}, String(m.priority ?? "")),
          el("td", {}, CLASSES.includes(m.troop_type) ? classLabel(m.troop_type) : m.troop_type),
          el("td", {}, fmt(current)),
          el("td", {}, numInput(m.target_total, (v) => { m.target_total = v || 0; edited(true); }, { min: 0, class: "wide" })),
          el("td", { class: gap ? "negative" : "positive" }, gap ? fmt(gap) : tr("troops.ok")),
          el("td", { class: "small" }, m.reason || ""),
        ]);
      })),
    ]));
    if (plan.proportionality_question || ratio.method) {
      out.push(details(tr("troops.why"), [
        plan.proportionality_question && el("p", {}, plan.proportionality_question),
        ratio.method && el("p", { class: "muted small" }, ratio.method),
      ]));
    }
    return out;
  }

  // -- Events --------------------------------------------------------------------------
  function heroSelect(currentId, options, onChange, blocked = new Set()) {
    const select = selectInput([["", "—"], ...options.map((h) => {
      const used = blocked.has(h.id) && h.id !== currentId;
      return [h.id, `${h.name}${used ? tr("events.inUse") : ""}`, used];
    })], currentId, (v) => { onChange(v || null); edited(true); });
    if (currentId && blocked.has(currentId)) select.classList.add("conflict");
    return select;
  }

  function heroRow(team, blockedByClass) {
    return el("div", { class: "team-row" }, CLASSES.map((cls) => el("span", { class: "team-slot" }, [
      classTag(cls),
      heroSelect(team[cls], heroesByClass(cls), (v) => { team[cls] = v; }, blockedByClass ? blockedByClass[cls] : new Set()),
    ])));
  }

  function troopRow(team, cap) {
    return el("div", { class: "team-row" }, [el("span", { class: "muted small" }, tr("events.troops")), ...CLASSES.map((cls) => {
      const pct = numInput(team.troop_split_percent[cls] ?? 0, () => edited(true), { min: 0, max: 100, step: 0.1, class: "pct", title: tr("events.percent") });
      const count = numInput(team.troops[cls] ?? 0, () => edited(true), { min: 0, max: cap, class: "wide", title: tr("events.amount") });
      pct.addEventListener("input", () => {
        team.troop_split_percent[cls] = numOrNull(pct.value) || 0;
        team.troops[cls] = Math.round(cap * team.troop_split_percent[cls] / 100);
        count.value = team.troops[cls];
      });
      count.addEventListener("input", () => {
        team.troops[cls] = numOrNull(count.value) || 0;
        team.troop_split_percent[cls] = cap > 0 ? round1(team.troops[cls] / cap * 100) : 0;
        pct.value = team.troop_split_percent[cls];
      });
      return el("span", { class: "team-slot" }, [classTag(cls), pct, el("span", { class: "muted small" }, "%"), count]);
    })]);
  }

  function capInput(ev, label) {
    return el("div", { class: "task-fields" }, field(label, numInput(ev.troop_cap, (v) => { ev.troop_cap = v || 0; edited(true); }, { min: 0, class: "wide" })));
  }

  function troopSummary(rows) {
    const totals = { infantry: 0, cavalry: 0, archer: 0 };
    rows.forEach((r) => CLASSES.forEach((c) => { totals[c] += r.troops?.[c] || 0; }));
    return el("div", { class: "pills" }, CLASSES.map((cls) => {
      const available = stock()[cls]?.total ?? 0;
      const over = totals[cls] > available;
      return el("span", { class: `pill ${over ? "over" : ""}` },
        `${classLabel(cls)}: ${fmt(totals[cls])} / ${fmt(available)}${over ? tr("events.overStock") : ""}`);
    }));
  }

  function usedHeroes(teams) {
    const used = { infantry: new Set(), cavalry: new Set(), archer: new Set() };
    teams.forEach((team) => CLASSES.forEach((c) => { if (team[c]) used[c].add(team[c]); }));
    return (team) => Object.fromEntries(CLASSES.map((c) => [c, new Set([...used[c]].filter((id) => id !== team[c]))]));
  }

  function eventCard(title, meta, children, rationale) {
    const texts = [].concat(rationale || []).filter(Boolean);
    return el("section", { class: "event-card" }, [
      el("h4", {}, title),
      meta && el("p", { class: "muted small" }, meta),
      ...children,
      texts.length ? details(tr("events.why"), texts.map((text) => el("p", {}, text))) : null,
    ]);
  }

  function queueBanner(count, allowed, what) {
    if (count <= allowed) return null;
    return el("div", { class: "callout warn" }, tr("events.queueBanner", { allowed, what, count }));
  }

  function arenaCard(ev) {
    return eventCard("Arena", tr("events.arenaMeta", { size: ev.march_size }), [
      el("div", { class: "team-row" }, ev.team.map((id, i) => heroSelect(id, heroes(), (v) => { ev.team[i] = v; }))),
    ], ev.rationale);
  }

  function kingsCastleCard(ev) {
    const rows = [];
    for (const [key, labelKey] of [["rally_lead", "events.rallyLead"], ["joiner", "events.joiner"]]) {
      const team = ev[key];
      if (!team) continue;
      rows.push(el("h5", {}, tr(labelKey) + (team.position_1_buff_hero ? tr("events.position1", { hero: heroName(team.position_1_buff_hero) }) : "")));
      rows.push(heroRow(team), troopRow(team, ev.troop_cap));
    }
    const teams = ["rally_lead", "joiner"].filter((k) => ev[k]).map((k) => ev[k]);
    return eventCard(tr("events.kingsCastle"), tr("events.kcMeta", { size: ev.march_size }),
      [capInput(ev, tr("events.capMarch")), ...rows, troopSummary(teams)],
      teams.map((team) => team.rationale));
  }

  function multiTeamCard(title, ev, labelKey, unitKey, maxTeams, what) {
    const blocked = usedHeroes(ev.teams);
    const unit = tr(unitKey);
    return eventCard(title, tr("events.multiMeta", { size: ev.march_size, unit: unit.toLowerCase(), count: ev.teams.length }), [
      queueBanner(ev.teams.length, maxTeams, what),
      capInput(ev, labelKey === "group" && ev.kingdom_troop_cap_per_group ? tr("events.capGroup") : tr("events.capMarch")),
      ...ev.teams.flatMap((team) => [
        el("h5", {}, `${unit} ${team[labelKey]}`),
        heroRow(team, blocked(team)),
        troopRow(team, ev.troop_cap),
        team.note ? el("p", { class: "muted small" }, team.note) : null,
      ]),
      troopSummary(ev.teams),
    ], [ev.split_rationale]);
  }

  function panelEvents() {
    const f = forms();
    const ev = f.events;
    const rules = f.rules;
    const out = [];
    const ruleTexts = [
      rules.march_composition,
      ...(rules.troop_rules || []),
      rules.rally_lead_vs_joiner,
      rules.bear_hunt_exception,
      rules.troop_caps?.bear_hunt_cap_note,
    ].filter(Boolean);
    if (ruleTexts.length) out.push(details(tr("events.rules"), [el("ul", {}, ruleTexts.map((text) => el("li", {}, text)))]));
    if (ev.arena) out.push(arenaCard(ev.arena));
    if (ev.kings_castle) out.push(kingsCastleCard(ev.kings_castle));
    if (ev.swordland_showdown) out.push(multiTeamCard("Swordland Showdown", ev.swordland_showdown, "queue", "events.queue", marchQueues(), tr("events.queuesWhat")));
    if (ev.tri_alliance_clash) out.push(multiTeamCard("Tri-Alliance Clash", ev.tri_alliance_clash, "group", "events.group", Infinity, ""));
    if (ev.bear_hunt) out.push(multiTeamCard("Bear Hunt", ev.bear_hunt, "group", "events.group", marchQueues() + 1, tr("events.bearWhat")));
    if (f.cross_event_conflict_note) out.push(el("div", { class: "callout warn" }, [el("strong", {}, tr("events.warning")), f.cross_event_conflict_note]));
    return out.length ? out : [el("p", { class: "muted" }, tr("events.none"))];
  }

  const PANELS = {
    profile: panelProfile,
    heroes: panelHeroes,
    hero_plan: panelHeroPlan,
    resource_stock: panelResourceStock,
    troop_stock: panelTroopStock,
    troop_plan: panelTroopPlan,
    events: panelEvents,
  };

  window.addEventListener("beforeunload", flushSave);
  return { mount };
})();
