const DAY_MS = 24 * 60 * 60 * 1000;

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const parseDate = (value) => new Date(`${value}T12:00:00`);

const isoDate = (value) => {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const calendarStart = () => {
  const value = new Date();
  value.setHours(12, 0, 0, 0);
  value.setDate(value.getDate() - ((value.getDay() + 6) % 7));
  return isoDate(value);
};

const formatDate = (value, options = {}) =>
  parseDate(value).toLocaleDateString(undefined, options);

const formatDateTime = (value) =>
  new Date(value).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

class SharedSchedulePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._data = undefined;
    this._entryId = undefined;
    this._tab = "schedule";
    this._party = undefined;
    this._selected = new Set();
    this._rangeAnchor = undefined;
    this._editingDate = undefined;
    this._loading = false;
    this._error = undefined;
  }

  set hass(value) {
    const firstLoad = !this._hass;
    this._hass = value;
    if (firstLoad && this.isConnected) this._load();
  }

  set narrow(value) {
    this.toggleAttribute("narrow", value);
  }

  set panel(value) {
    this._panel = value;
  }

  connectedCallback() {
    this._render();
    if (this._hass && !this._data) this._load();
  }

  async _call(message) {
    return this._hass.connection.sendMessagePromise(message);
  }

  async _load() {
    if (this._loading) return;
    this._loading = true;
    this._error = undefined;
    this._render();
    try {
      const response = await this._call({
        type: "shared_schedule/get",
        start: calendarStart(),
        days: 42,
      });
      this._data = response.schedules;
      if (!this._entryId && this._data.length) {
        this._entryId = this._data[0].entry_id;
      }
    } catch (error) {
      this._error = error?.message || String(error);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  get _schedule() {
    return this._data?.find((item) => item.entry_id === this._entryId);
  }

  _partyClass(party) {
    return party === "a" ? "party-a" : "party-b";
  }

  _calendarDay(day) {
    const selected = this._selected.has(day.date);
    const today = day.date === isoDate(new Date());
    const normalMatches = day.normal_party === this._party;
    const disabled = this._party && normalMatches && !day.overridden;
    const classes = ["day", this._partyClass(day.party)];
    if (day.overridden) classes.push("overridden");
    if (selected) classes.push("selected");
    if (disabled) classes.push("disabled");
    if (today) classes.push("today");
    return `
      <button class="${classes.join(" ")}" data-date="${day.date}"
        aria-label="${escapeHtml(formatDate(day.date, { dateStyle: "full" }))}: ${escapeHtml(day.party_name)}"
        ${disabled ? "disabled" : ""}>
        <span class="date-number">${parseDate(day.date).getDate()}</span>
        <span class="owner owner-name">${escapeHtml(day.party_name)}</span>
        ${
          day.overridden
            ? `<span class="owner override-detail">Override · ${escapeHtml(day.normal_party_name)} → ${escapeHtml(day.party_name)}</span>`
            : ""
        }
      </button>`;
  }

  _summary() {
    const schedule = this._schedule;
    const dates = [...this._selected].sort();
    if (!schedule || !this._party || !dates.length) return "";
    const selectedParty = schedule.parties[this._party];
    const otherParty = schedule.parties[this._party === "a" ? "b" : "a"];
    const first = dates[0];
    const last = dates[dates.length - 1];
    const contiguous = dates.every(
      (value, index) =>
        index === 0 || parseDate(value) - parseDate(dates[index - 1]) === DAY_MS,
    );
    const dateOptions = { weekday: "long", day: "numeric", month: "long" };
    let when;
    if (dates.length === 1) {
      when = `on ${formatDate(first, dateOptions)}`;
    } else if (contiguous) {
      when = `from ${formatDate(first, dateOptions)} through ${formatDate(last, dateOptions)}`;
    } else {
      when = `on ${dates.length} selected dates`;
    }
    return `${selectedParty} will have responsibility ${when}. These dates would normally belong to ${otherParty}. The normal alternating schedule resumes afterward.`;
  }

  _groupOverrides() {
    const schedule = this._schedule;
    if (!schedule) return [];
    const dates = Object.entries(schedule.date_overrides)
      .filter(([value]) => value >= isoDate(new Date()))
      .sort(([left], [right]) => left.localeCompare(right));
    const groups = [];
    for (const [value, party] of dates) {
      const previous = groups.at(-1);
      if (
        previous &&
        previous.party === party &&
        parseDate(value) - parseDate(previous.dates.at(-1)) === DAY_MS
      ) {
        previous.dates.push(value);
      } else {
        groups.push({ party, dates: [value] });
      }
    }
    return groups;
  }

  _renderSchedule(schedule) {
    const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const summary = this._summary();
    return `
      <section class="card owner-picker">
        <div>
          <h2>Add an override</h2>
          <p>Choose who will have responsibility, then pick an individual date or two endpoints for a range.</p>
        </div>
        <div class="party-buttons">
          ${Object.entries(schedule.parties)
            .map(
              ([key, name]) => `
                <button class="party-choice ${this._party === key ? "active" : ""} ${this._partyClass(key)}"
                  data-party="${key}">${escapeHtml(name)}</button>`,
            )
            .join("")}
        </div>
      </section>
      <section class="card calendar-card">
        <div class="calendar-heading">
          <div>
            <h2>Upcoming six weeks</h2>
            <p>${
              this._party
                ? `Dates normally belonging to ${escapeHtml(schedule.parties[this._party])} are muted. Cards always show the actual owner.`
                : "Choose a party to begin selecting dates. Cards show the actual owner."
            }</p>
          </div>
          <div class="legend">
            <span><i class="swatch party-a"></i>${escapeHtml(schedule.parties.a)} · actual owner</span>
            <span><i class="swatch party-b"></i>${escapeHtml(schedule.parties.b)} · actual owner</span>
            <span><i class="swatch override-swatch"></i>Override · normal schedule changed</span>
          </div>
        </div>
        <div class="calendar">
          ${weekdays.map((day) => `<div class="weekday">${day}</div>`).join("")}
          ${schedule.calendar.map((day) => this._calendarDay(day)).join("")}
        </div>
      </section>
      ${
        this._editingDate
          ? this._overrideEditor(schedule, this._editingDate)
          : ""
      }
      ${
        summary
          ? `<section class="selection-bar card"><p>${escapeHtml(summary)}</p>
              <div><button class="secondary" data-action="clear-selection">Clear</button>
              <button class="primary" data-action="save-selection">Save override</button></div></section>`
          : ""
      }`;
  }

  _overrideEditor(schedule, value) {
    const party = schedule.date_overrides[value];
    const replacement = party === "a" ? "b" : "a";
    return `<section class="card override-editor">
      <div><h3>${escapeHtml(formatDate(value, { dateStyle: "full" }))}</h3>
      <p>Currently overridden to ${escapeHtml(schedule.parties[party])}.</p></div>
      <div>
        <button class="secondary" data-action="close-editor">Cancel</button>
        <button class="danger" data-action="remove-one" data-date="${value}">Remove</button>
        <button class="primary" data-action="replace-one" data-date="${value}" data-party="${replacement}">
          Change to ${escapeHtml(schedule.parties[replacement])}
        </button>
      </div>
    </section>`;
  }

  _renderOverrides(schedule) {
    const groups = this._groupOverrides();
    if (!groups.length) {
      return `<section class="card empty"><h2>No upcoming overrides</h2><p>The recurring schedule applies to every upcoming date.</p></section>`;
    }
    return `<section class="card"><h2>Upcoming overrides</h2><div class="override-list">
      ${groups
        .map((group) => {
          const first = group.dates[0];
          const last = group.dates.at(-1);
          const range =
            first === last
              ? formatDate(first, { weekday: "short", day: "numeric", month: "short" })
              : `${formatDate(first, { weekday: "short", day: "numeric", month: "short" })} – ${formatDate(last, { weekday: "short", day: "numeric", month: "short" })}`;
          return `<div class="override-row">
            <i class="party-dot ${this._partyClass(group.party)}"></i>
            <div><strong>${escapeHtml(schedule.parties[group.party])}</strong><span>${escapeHtml(range)}</span></div>
            <button class="secondary" data-action="edit-group" data-party="${group.party}" data-dates="${group.dates.join(",")}">Edit</button>
            <button class="danger" data-action="remove-group" data-dates="${group.dates.join(",")}">Delete</button>
          </div>`;
        })
        .join("")}
    </div></section>`;
  }

  _renderSettings(schedule) {
    const settings = schedule.settings;
    const sourceLabels = {
      automatic: "Automatic holiday calendar",
      manual_fallback: "Manual fallback dates",
      unavailable: "Unavailable",
      disabled: "Disabled",
    };
    const rows = [
      ["Party A", settings.party_a],
      ["Party B", settings.party_b],
      ["Recurrence", `Every ${settings.recurrence_weeks} week${settings.recurrence_weeks === 1 ? "" : "s"}`],
      ["Handover time", settings.handover_time],
      ["Holiday country", settings.country],
      ["Public-holiday adjustment", settings.shift_public_holidays ? "Enabled" : "Disabled"],
      ["Holiday data", sourceLabels[schedule.holiday_status.source]],
    ];
    return `<section class="card settings-card">
      <div><h2>Schedule settings</h2><p>Edit these through Home Assistant’s integration options.</p></div>
      <dl>${rows
        .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`)
        .join("")}</dl>
      <button class="primary" data-action="open-settings">Open integration settings</button>
    </section>
    <section class="card colour-card">
      <div><h2>Party colours</h2><p>Colours support the party names and ownership labels; they are never the only indicator.</p></div>
      <div class="colour-fields">
        <label>${escapeHtml(schedule.parties.a)}
          <input type="color" data-field="party-a-color" value="${escapeHtml(settings.party_a_color)}">
        </label>
        <label>${escapeHtml(schedule.parties.b)}
          <input type="color" data-field="party-b-color" value="${escapeHtml(settings.party_b_color)}">
        </label>
      </div>
      <button class="primary" data-action="save-party-colours">Save colours</button>
    </section>
    <section class="card fallback-card" id="fallback-holidays">
      <div><h2>Fallback public holidays</h2>
        <p>These dates are used only when automatic holiday data is unavailable.</p></div>
      <div class="fallback-form">
        <label>Date<input type="date" data-field="fallback-date" required></label>
        <label>Display name <small>Optional</small><input type="text" data-field="fallback-name" maxlength="120" placeholder="e.g. August bank holiday"></label>
        <button class="primary" data-action="add-fallback">Add fallback date</button>
      </div>
      <div class="fallback-list">
        ${schedule.fallback_holidays.length
          ? schedule.fallback_holidays.map((holiday) => `<div class="fallback-row">
              <div><strong>${escapeHtml(formatDate(holiday.date, { dateStyle: "long" }))}</strong>
                ${holiday.name ? `<span>${escapeHtml(holiday.name)}</span>` : ""}</div>
              <button class="danger" data-action="remove-fallback" data-date="${holiday.date}">Remove</button>
            </div>`).join("")
          : "<p class=\"empty-fallbacks\">No fallback dates have been added.</p>"}
      </div>
    </section>`;
  }

  _holidayNotice(schedule) {
    const source = schedule.holiday_status.source;
    if (source === "manual_fallback") {
      return `<section class="notice mild"><div><strong>Using fallback public-holiday dates</strong>
        <p>Automatic holiday data is unavailable, so saved fallback dates are being used.</p></div>
        <button class="secondary" data-action="manage-fallbacks">Manage dates</button></section>`;
    }
    if (source === "unavailable") {
      return `<section class="notice warning"><div><strong>Public-holiday adjustments are unavailable</strong>
        <p>Shared Schedule still works, but public-holiday adjustments cannot currently be made. Some handover dates may be inaccurate.</p></div>
        <button class="primary" data-action="manage-fallbacks">Add fallback dates</button></section>`;
    }
    return "";
  }

  _render() {
    if (!this.shadowRoot) return;
    const schedule = this._schedule;
    const partyColours = schedule
      ? `--party-a-color:${escapeHtml(schedule.settings.party_a_color)}; --party-b-color:${escapeHtml(schedule.settings.party_b_color)};`
      : "";
    this.shadowRoot.innerHTML = `<style>${this._styles()}</style>
      <div class="page" style="${partyColours}">
        <header class="topbar"><div><span class="eyebrow">Shared Schedule</span><h1>${escapeHtml(schedule?.title || "Schedule")}</h1></div>
          ${
            this._data?.length > 1
              ? `<select data-action="entry">${this._data.map((item) => `<option value="${item.entry_id}" ${item.entry_id === this._entryId ? "selected" : ""}>${escapeHtml(item.title)}</option>`).join("")}</select>`
              : ""
          }</header>
        ${
          this._loading && !schedule
            ? `<section class="card empty"><p>Loading schedule…</p></section>`
            : this._error
              ? `<section class="card error"><h2>Could not load the schedule</h2><p>${escapeHtml(this._error)}</p><button class="primary" data-action="retry">Try again</button></section>`
              : !schedule
                ? `<section class="card empty"><h2>No loaded schedules</h2><p>Add or enable a Shared Schedule integration entry first.</p></section>`
                : `${this._overview(schedule)}${this._holidayNotice(schedule)}${this._tabs()}${
                    this._tab === "schedule"
                      ? this._renderSchedule(schedule)
                      : this._tab === "overrides"
                        ? this._renderOverrides(schedule)
                        : this._renderSettings(schedule)
                  }`
        }
      </div>`;
    this._bind();
  }

  _overview(schedule) {
    const effectiveDiffers = schedule.normal_handover !== schedule.effective_handover;
    return `<section class="overview">
      <article class="hero card"><span>Current actual owner</span><strong>${escapeHtml(schedule.actual_current_party_name)}</strong>
        ${schedule.actual_current_party !== schedule.current_party ? "<small>Date override active today</small>" : "<small>Recurring schedule</small>"}</article>
      <article class="card metric"><span>Next normal handover</span><strong>${escapeHtml(formatDateTime(schedule.normal_handover))}</strong>
        ${schedule.shifted_for_public_holiday ? "<small>Adjusted for a public holiday</small>" : "<small>Recurring cadence</small>"}</article>
      <article class="card metric"><span>Next effective handover</span><strong>${escapeHtml(formatDateTime(schedule.effective_handover))}</strong>
        <small>${effectiveDiffers ? "Handover override active" : "Same as normal"}</small></article>
    </section>`;
  }

  _tabs() {
    return `<nav class="tabs" aria-label="Schedule sections">
      ${["schedule", "overrides", "settings"]
        .map((tab) => `<button data-tab="${tab}" class="${this._tab === tab ? "active" : ""}">${tab[0].toUpperCase()}${tab.slice(1)}</button>`)
        .join("")}
    </nav>`;
  }

  _bind() {
    this.shadowRoot.querySelectorAll("[data-tab]").forEach((button) =>
      button.addEventListener("click", () => {
        this._tab = button.dataset.tab;
        this._editingDate = undefined;
        this._render();
      }),
    );
    this.shadowRoot.querySelectorAll("[data-party]").forEach((button) => {
      if (!button.dataset.action) {
        button.addEventListener("click", () => {
          this._party = button.dataset.party;
          this._selected.clear();
          this._rangeAnchor = undefined;
          this._render();
        });
      }
    });
    this.shadowRoot.querySelectorAll(".day:not(:disabled)").forEach((button) =>
      button.addEventListener("click", () => this._selectDate(button.dataset.date)),
    );
    this.shadowRoot.querySelectorAll("button[data-action]").forEach((element) =>
      element.addEventListener("click", () => this._action(element)),
    );
    this.shadowRoot.querySelector('select[data-action="entry"]')?.addEventListener("change", (event) => {
      this._entryId = event.target.value;
      this._party = undefined;
      this._selected.clear();
      this._render();
    });
  }

  _selectDate(value) {
    const day = this._schedule.calendar.find((item) => item.date === value);
    if (day.overridden) {
      this._editingDate = value;
      this._render();
      return;
    }
    if (!this._party) return;
    if (this._selected.has(value)) {
      this._selected.delete(value);
      this._rangeAnchor = undefined;
    } else if (this._rangeAnchor) {
      const low = this._rangeAnchor < value ? this._rangeAnchor : value;
      const high = this._rangeAnchor < value ? value : this._rangeAnchor;
      this._schedule.calendar
        .filter((item) => item.date >= low && item.date <= high && item.normal_party !== this._party)
        .forEach((item) => this._selected.add(item.date));
      this._rangeAnchor = undefined;
    } else {
      this._selected.add(value);
      this._rangeAnchor = value;
    }
    this._render();
  }

  async _action(element) {
    const action = element.dataset.action;
    if (action === "retry") return this._load();
    if (action === "clear-selection") {
      this._selected.clear();
      this._rangeAnchor = undefined;
      return this._render();
    }
    if (action === "close-editor") {
      this._editingDate = undefined;
      return this._render();
    }
    if (action === "open-settings") {
      window.history.pushState(null, "", "/config/integrations/integration/shared_schedule");
      window.dispatchEvent(new Event("location-changed"));
      return;
    }
    if (action === "manage-fallbacks") {
      this._tab = "settings";
      this._render();
      this.shadowRoot.querySelector('[data-field="fallback-date"]')?.focus();
      return;
    }
    if (action === "edit-group") {
      this._tab = "schedule";
      this._party = element.dataset.party;
      this._selected = new Set(element.dataset.dates.split(","));
      this._rangeAnchor = undefined;
      return this._render();
    }
    try {
      if (action === "save-selection") {
        await this._setOverrides([...this._selected], this._party);
        this._selected.clear();
        this._rangeAnchor = undefined;
      } else if (action === "replace-one") {
        await this._setOverrides([element.dataset.date], element.dataset.party);
        this._editingDate = undefined;
      } else if (action === "remove-one" || action === "remove-group") {
        const dates = action === "remove-one" ? [element.dataset.date] : element.dataset.dates.split(",");
        await this._removeOverrides(dates);
        this._editingDate = undefined;
      } else if (action === "add-fallback") {
        const dateInput = this.shadowRoot.querySelector('[data-field="fallback-date"]');
        if (!dateInput.reportValidity()) return;
        const name = this.shadowRoot.querySelector('[data-field="fallback-name"]').value.trim();
        await this._setFallbackHoliday(dateInput.value, name);
      } else if (action === "remove-fallback") {
        await this._removeFallbackHoliday(element.dataset.date);
      } else if (action === "save-party-colours") {
        const partyAColor = this.shadowRoot.querySelector('[data-field="party-a-color"]').value;
        const partyBColor = this.shadowRoot.querySelector('[data-field="party-b-color"]').value;
        await this._setPartyColors(partyAColor, partyBColor);
      }
      await this._load();
    } catch (error) {
      this._error = error?.message || String(error);
      this._render();
    }
  }

  _setOverrides(dates, party) {
    return this._call({
      type: "shared_schedule/date_overrides/set",
      entry_id: this._entryId,
      party,
      dates,
    });
  }

  _removeOverrides(dates) {
    return this._call({
      type: "shared_schedule/date_overrides/remove",
      entry_id: this._entryId,
      dates,
    });
  }

  _setFallbackHoliday(date, name) {
    return this._call({
      type: "shared_schedule/fallback_holidays/set",
      entry_id: this._entryId,
      date,
      ...(name ? { name } : {}),
    });
  }

  _removeFallbackHoliday(date) {
    return this._call({
      type: "shared_schedule/fallback_holidays/remove",
      entry_id: this._entryId,
      date,
    });
  }

  _setPartyColors(partyAColor, partyBColor) {
    return this._call({
      type: "shared_schedule/party_colors/set",
      entry_id: this._entryId,
      party_a_color: partyAColor,
      party_b_color: partyBColor,
    });
  }

  _styles() {
    return `
      :host { display:block; min-height:100%; color:var(--primary-text-color); background:var(--primary-background-color); font-family:var(--paper-font-body1_-_font-family, sans-serif); }
      * { box-sizing:border-box; }
      button, select, input { font:inherit; }
      button { cursor:pointer; }
      .page { max-width:1180px; margin:0 auto; padding:28px 24px 56px; }
      .topbar { display:flex; justify-content:space-between; align-items:end; gap:20px; margin-bottom:20px; }
      .eyebrow, .card > span, .metric > span { color:var(--secondary-text-color); font-size:.78rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
      h1 { margin:4px 0 0; font-size:clamp(1.8rem, 4vw, 2.7rem); line-height:1; }
      h2, h3, p { margin-top:0; } h2 { margin-bottom:8px; } p { color:var(--secondary-text-color); line-height:1.5; }
      .card { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:18px; box-shadow:var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,.08)); }
      .overview { display:grid; grid-template-columns:1.15fr 1fr 1fr; gap:14px; }
      .overview article { padding:22px; min-height:130px; display:flex; flex-direction:column; }
      .overview strong { margin:auto 0 7px; font-size:1.22rem; }
      .notice { margin-top:14px; padding:18px 20px; display:flex; align-items:center; justify-content:space-between; gap:20px; border-radius:14px; }
      .notice p { margin:4px 0 0; }
      .notice.mild { background:color-mix(in srgb, var(--primary-color) 8%, var(--card-background-color)); border:1px solid color-mix(in srgb, var(--primary-color) 35%, var(--divider-color)); }
      .notice.warning { background:color-mix(in srgb, var(--warning-color, #f2a900) 12%, var(--card-background-color)); border:2px solid var(--warning-color, #f2a900); }
      .hero { background:linear-gradient(135deg, var(--primary-color), color-mix(in srgb, var(--primary-color) 72%, #171e3d)); color:var(--text-primary-color, white); border:0; }
      .hero span, .hero small { color:color-mix(in srgb, currentColor 75%, transparent); }
      small { color:var(--secondary-text-color); }
      .tabs { display:flex; gap:6px; margin:24px 0 14px; border-bottom:1px solid var(--divider-color); }
      .tabs button { padding:12px 16px; border:0; border-bottom:3px solid transparent; background:none; color:var(--secondary-text-color); }
      .tabs button.active { color:var(--primary-color); border-color:var(--primary-color); font-weight:700; }
      .owner-picker { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:20px 22px; margin-bottom:14px; }
      .owner-picker p { margin-bottom:0; }
      .party-buttons { display:flex; gap:10px; }
      .party-choice { min-width:130px; padding:12px 18px; border:2px solid transparent; border-radius:12px; color:var(--primary-text-color); background:var(--secondary-background-color); }
      .party-choice.active { border-color:var(--primary-color); box-shadow:0 0 0 2px color-mix(in srgb, var(--primary-color) 20%, transparent); font-weight:700; }
      .calendar-card { padding:20px; }
      .calendar-heading { display:flex; justify-content:space-between; align-items:start; gap:16px; }
      .calendar-heading p { margin-bottom:8px; }
      .legend { display:flex; flex-wrap:wrap; gap:12px; font-size:.78rem; color:var(--secondary-text-color); }
      .legend span { display:flex; align-items:center; gap:5px; }
      .swatch { width:12px; height:12px; border-radius:4px; display:inline-block; }
      .party-a { --party-color:var(--party-a-color); --party-soft:color-mix(in srgb, var(--party-a-color) 16%, var(--card-background-color)); }
      .party-b { --party-color:var(--party-b-color); --party-soft:color-mix(in srgb, var(--party-b-color) 16%, var(--card-background-color)); }
      .swatch.party-a, .swatch.party-b { background:var(--party-color); }
      .override-swatch { border:2px solid var(--warning-color, #f2a900); background:transparent; }
      .calendar { display:grid; grid-template-columns:repeat(7, minmax(0, 1fr)); gap:7px; }
      .weekday { text-align:center; padding:9px 0; color:var(--secondary-text-color); font-size:.76rem; font-weight:700; text-transform:uppercase; }
      .day { position:relative; min-height:90px; padding:9px; border:1px solid var(--divider-color); border-top:4px solid var(--party-color); border-radius:12px; background:var(--party-soft); color:var(--primary-text-color); text-align:left; display:flex; flex-direction:column; gap:5px; overflow:hidden; }
      .day:hover:not(:disabled) { transform:translateY(-1px); border-color:var(--primary-color); }
      .day.today .date-number { background:var(--primary-color); color:white; border-radius:50%; }
      .day.overridden { border:2px solid var(--warning-color, #f2a900); border-top-width:4px; }
      .day.selected { outline:3px solid var(--primary-color); outline-offset:1px; }
      .day.disabled { opacity:.42; cursor:not-allowed; filter:saturate(.4); }
      .date-number { width:27px; height:27px; display:grid; place-items:center; font-weight:700; }
      .owner { font-size:.72rem; line-height:1.25; white-space:normal; }
      .owner-name { font-weight:700; }
      .override-detail { color:var(--warning-color, #c77800); font-size:.62rem; font-weight:700; }
      .selection-bar, .override-editor { position:sticky; bottom:16px; z-index:2; margin-top:14px; padding:16px 20px; display:flex; justify-content:space-between; align-items:center; gap:18px; box-shadow:0 10px 30px rgba(0,0,0,.18); }
      .selection-bar p, .override-editor p { margin:0; color:var(--primary-text-color); }
      .selection-bar div, .override-editor > div:last-child { display:flex; gap:8px; flex-shrink:0; }
      button.primary, button.secondary, button.danger { border-radius:10px; padding:10px 14px; font-weight:700; }
      button.primary { border:0; background:var(--primary-color); color:white; }
      button.secondary { border:1px solid var(--divider-color); background:var(--secondary-background-color); color:var(--primary-text-color); }
      button.danger { border:1px solid var(--error-color); background:transparent; color:var(--error-color); }
      .override-list { display:flex; flex-direction:column; }
      .override-list + * { margin-top:12px; }
      .card:has(.override-list), .settings-card, .colour-card, .fallback-card, .empty, .error { padding:22px; }
      .override-row { display:grid; grid-template-columns:auto 1fr auto auto; align-items:center; gap:12px; padding:15px 0; border-top:1px solid var(--divider-color); }
      .override-row:first-child { border-top:0; }
      .override-row div { display:flex; flex-direction:column; gap:3px; }
      .override-row span { color:var(--secondary-text-color); font-size:.86rem; }
      .party-dot { width:13px; height:42px; border-radius:8px; background:var(--party-color); }
      .settings-card { display:grid; grid-template-columns:1fr 1.4fr; gap:24px; align-items:start; }
      .settings-card dl { margin:0; }
      .settings-card dl div { display:flex; justify-content:space-between; gap:20px; padding:10px 0; border-bottom:1px solid var(--divider-color); }
      dt { color:var(--secondary-text-color); } dd { margin:0; text-align:right; font-weight:600; }
      .settings-card > button { grid-column:2; justify-self:end; }
      .colour-card { display:grid; grid-template-columns:1fr 1.4fr auto; gap:20px; align-items:end; margin-top:14px; }
      .colour-card p { margin-bottom:0; }
      .colour-fields { display:flex; gap:14px; }
      .colour-fields label { display:flex; align-items:center; gap:8px; font-weight:700; }
      .colour-fields input { width:44px; height:34px; padding:2px; border:1px solid var(--divider-color); border-radius:8px; background:var(--card-background-color); }
      .fallback-card { margin-top:14px; }
      .fallback-form { display:grid; grid-template-columns:1fr 1.5fr auto; gap:12px; align-items:end; margin:18px 0; }
      .fallback-form label { display:flex; flex-direction:column; gap:6px; color:var(--secondary-text-color); font-size:.86rem; font-weight:600; }
      .fallback-form label small { font-weight:400; }
      .fallback-list { border-top:1px solid var(--divider-color); }
      .fallback-row { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:14px 0; border-bottom:1px solid var(--divider-color); }
      .fallback-row div { display:flex; flex-direction:column; gap:3px; }
      .fallback-row span, .empty-fallbacks { color:var(--secondary-text-color); }
      .empty-fallbacks { margin:16px 0 0; }
      select, input { padding:9px 12px; border:1px solid var(--divider-color); border-radius:9px; background:var(--card-background-color); color:var(--primary-text-color); }
      @media (max-width:780px) {
        .page { padding:18px 10px 40px; }
        .overview { grid-template-columns:1fr; }
        .overview article { min-height:105px; }
        .owner-picker, .calendar-heading, .selection-bar, .override-editor, .notice { align-items:stretch; flex-direction:column; }
        .party-buttons { width:100%; } .party-choice { min-width:0; flex:1; }
        .calendar-card { padding:10px 6px; }
        .calendar { gap:3px; }
        .day { min-height:70px; padding:5px 3px; border-radius:8px; }
        .owner { font-size:.58rem; overflow-wrap:anywhere; }
        .override-detail { font-size:.52rem; }
        .selection-bar, .override-editor { bottom:6px; }
        .selection-bar div, .override-editor > div:last-child { flex-wrap:wrap; }
        .override-row { grid-template-columns:auto 1fr auto; }
        .override-row button:last-child { grid-column:3; }
        .settings-card { grid-template-columns:1fr; }
        .settings-card > button { grid-column:1; justify-self:stretch; }
        .colour-card { grid-template-columns:1fr; }
        .colour-card > button { justify-self:stretch; }
        .fallback-form { grid-template-columns:1fr; }
      }
    `;
  }
}

customElements.define("shared-schedule-panel", SharedSchedulePanel);
