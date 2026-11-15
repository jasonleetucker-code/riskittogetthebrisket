/**
 * Combobox — searchable single-select (WAI-ARIA combobox + listbox).
 *
 * Modelled on the calculator's existing inline search
 * (app/trade/trade-sections.jsx: role="combobox", aria-autocomplete="list",
 * aria-expanded / aria-controls / aria-activedescendant, Arrow keys + Enter).
 * /trade is not migrated onto it here (Lane 6 follow-up) — this is the shared
 * primitive new surfaces use instead of a page-local copy.
 *
 * Usage:
 *   <Combobox
 *     label="Which team is yours?"
 *     value={rosterId}
 *     onChange={setRosterId}
 *     options={[{ value: 4, label: "Team name", description: "Owner",
 *                 disabled: false, disabledReason: "in trade" }]}
 *     placeholder="Search teams"
 *   />
 *
 * Props:
 *   options        [{value, label, description?, disabled?, disabledReason?}]
 *   value          the selected option's value (or null)
 *   onChange(v)    called with the chosen value (never a disabled option)
 *   label          visible label (required for a11y)
 *   hint           optional helper text under the field
 *   placeholder    input placeholder
 *   emptyText      text when the query matches nothing
 *   id             optional id for the input
 *
 * Behavior: typing filters by label/description (case-insensitive substring);
 * ArrowDown/ArrowUp move, Home/End jump, Enter selects, Escape closes and
 * restores the selected label.  The list is a <ul role="listbox"> with no
 * aria-posinset / aria-setsize: position in a list is not information this
 * primitive publishes.  Disabled options stay visible and announce why.
 */
"use client";

import React, { useId, useMemo, useRef, useState } from "react";

export function Combobox({
  options = [],
  value = null,
  onChange,
  label,
  hint,
  placeholder = "Search",
  emptyText = "No matches.",
  id,
  className = "",
}) {
  const autoId = useId();
  const inputId = id || `ds-combobox-${autoId}`;
  const listId = `${inputId}-list`;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const selected = options.find((o) => o.value === value) || null;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const inputRef = useRef(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) =>
      `${o.label} ${o.description || ""}`.toLowerCase().includes(q),
    );
  }, [options, query]);

  const enabledIndex = (from, step) => enabledIndexIn(filtered, from, step);

  const openList = () => {
    setOpen(true);
    setQuery("");
    const sel = options.findIndex((o) => o.value === value);
    setActive(sel >= 0 && !options[sel].disabled ? sel : enabledIndexIn(options, 0, 1));
  };

  const choose = (opt) => {
    if (!opt || opt.disabled) return;
    onChange?.(opt.value);
    setOpen(false);
    setQuery("");
    setActive(-1);
  };

  const onKeyDown = (e) => {
    if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter")) {
      e.preventDefault();
      openList();
      return;
    }
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive(enabledIndex(active + 1, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive(enabledIndex(active - 1 < 0 ? filtered.length - 1 : active - 1, -1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(enabledIndex(0, 1));
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(enabledIndex(filtered.length - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (active >= 0) choose(filtered[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      setQuery("");
    }
  };

  const shown = open ? query : selected ? selected.label : "";
  const activeId = open && active >= 0 && filtered[active] ? `${inputId}-opt-${active}` : undefined;

  return (
    <div className={`ds-combobox ${className}`.trim()}>
      {label ? (
        <label className="ds-label" htmlFor={inputId}>
          {label}
        </label>
      ) : null}
      <div className="ds-combobox__control">
        <input
          ref={inputRef}
          id={inputId}
          className="ds-input ds-combobox__input"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={activeId}
          aria-describedby={hintId}
          autoComplete="off"
          spellCheck="false"
          placeholder={selected && !open ? selected.label : placeholder}
          value={shown}
          onFocus={() => {
            if (!open) openList();
          }}
          onClick={() => {
            if (!open) openList();
          }}
          onBlur={() => {
            setOpen(false);
            setQuery("");
          }}
          onChange={(e) => {
            if (!open) setOpen(true);
            setQuery(e.target.value);
            setActive(-1);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      {hint ? (
        <p id={hintId} className="ds-combobox__hint">
          {hint}
        </p>
      ) : null}
      <ul
        id={listId}
        role="listbox"
        aria-label={label || placeholder}
        className="ds-combobox__list"
        hidden={!open}
      >
        {open && filtered.length === 0 ? (
          <li className="ds-combobox__empty" role="presentation">
            {emptyText}
          </li>
        ) : null}
        {open
          ? filtered.map((opt, i) => (
              <li
                key={String(opt.value)}
                id={`${inputId}-opt-${i}`}
                role="option"
                aria-selected={opt.value === value}
                aria-disabled={opt.disabled ? true : undefined}
                className={`ds-combobox__option${i === active ? " ds-combobox__option--active" : ""}`}
                // mousedown, not click: the input's blur would close the
                // list before a click lands.
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(opt);
                }}
              >
                <span className="ds-combobox__optionLabel">{opt.label}</span>
                {opt.description || (opt.disabled && opt.disabledReason) ? (
                  <span className="ds-combobox__optionMeta">
                    {[opt.description, opt.disabled ? opt.disabledReason : null].filter(Boolean).join(" · ")}
                  </span>
                ) : null}
              </li>
            ))
          : null}
      </ul>
    </div>
  );
}

function enabledIndexIn(list, from, step) {
  for (let i = from, n = 0; n < list.length; i += step, n += 1) {
    const idx = (i + list.length) % list.length;
    if (!list[idx].disabled) return idx;
  }
  return -1;
}

export default Combobox;
