/**
 * DataTable behavior spec: sorting (direction conventions, stability,
 * null handling), aria-sort stamping, keyboard operability of both sort
 * headers and interactive rows, density classes, numeric alignment.
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable, sortRows } from "@/components/ds";

const COLUMNS = [
  { key: "name", header: "Player", sortable: true },
  { key: "value", header: "Value", numeric: true, sortable: true },
  { key: "team", header: "Team" },
];

const ROWS = [
  { id: "a", name: "Chase", value: 9430, team: "CIN" },
  { id: "b", name: "Jefferson", value: 9541, team: "MIN" },
  { id: "c", name: "Bijan", value: 9155, team: "ATL" },
];

function bodyCellText(colIndex) {
  const rows = screen.getAllByRole("row").slice(1); // drop header row
  return rows.map((r) => within(r).getAllByRole("cell")[colIndex].textContent);
}

describe("DataTable sorting", () => {
  it("renders unsorted by default with no aria-sort", () => {
    render(<DataTable caption="t" columns={COLUMNS} rows={ROWS} />);
    for (const th of screen.getAllByRole("columnheader")) {
      expect(th).not.toHaveAttribute("aria-sort");
    }
    expect(bodyCellText(0)).toEqual(["Chase", "Jefferson", "Bijan"]);
  });

  it("first activation sorts text columns ascending and stamps aria-sort", async () => {
    const user = userEvent.setup();
    render(<DataTable caption="t" columns={COLUMNS} rows={ROWS} />);
    await user.click(screen.getByRole("button", { name: "Player" }));
    const th = screen.getByRole("columnheader", { name: "Player" });
    expect(th).toHaveAttribute("aria-sort", "ascending");
    expect(bodyCellText(0)).toEqual(["Bijan", "Chase", "Jefferson"]);
  });

  it("first activation sorts numeric columns DESCENDING (terminal convention)", async () => {
    const user = userEvent.setup();
    render(<DataTable caption="t" columns={COLUMNS} rows={ROWS} />);
    await user.click(screen.getByRole("button", { name: "Value" }));
    expect(
      screen.getByRole("columnheader", { name: "Value" })
    ).toHaveAttribute("aria-sort", "descending");
    expect(bodyCellText(1)).toEqual(["9541", "9430", "9155"]);
  });

  it("second activation flips direction and re-stamps aria-sort", async () => {
    const user = userEvent.setup();
    render(<DataTable caption="t" columns={COLUMNS} rows={ROWS} />);
    const btn = screen.getByRole("button", { name: "Value" });
    await user.click(btn);
    await user.click(btn);
    expect(
      screen.getByRole("columnheader", { name: "Value" })
    ).toHaveAttribute("aria-sort", "ascending");
    expect(bodyCellText(1)).toEqual(["9155", "9430", "9541"]);
  });

  it("moving sort to another column clears aria-sort on the previous one", async () => {
    const user = userEvent.setup();
    render(<DataTable caption="t" columns={COLUMNS} rows={ROWS} />);
    await user.click(screen.getByRole("button", { name: "Value" }));
    await user.click(screen.getByRole("button", { name: "Player" }));
    expect(
      screen.getByRole("columnheader", { name: "Value" })
    ).not.toHaveAttribute("aria-sort");
    expect(
      screen.getByRole("columnheader", { name: "Player" })
    ).toHaveAttribute("aria-sort", "ascending");
  });

  it("sort headers are real buttons and keyboard-operable (Enter)", async () => {
    const user = userEvent.setup();
    render(<DataTable caption="t" columns={COLUMNS} rows={ROWS} />);
    const btn = screen.getByRole("button", { name: "Value" });
    btn.focus();
    await user.keyboard("{Enter}");
    expect(
      screen.getByRole("columnheader", { name: "Value" })
    ).toHaveAttribute("aria-sort", "descending");
  });

  it("non-sortable columns render no button", () => {
    render(<DataTable caption="t" columns={COLUMNS} rows={ROWS} />);
    const th = screen.getByRole("columnheader", { name: "Team" });
    expect(within(th).queryByRole("button")).toBeNull();
  });

  it("announces the active sort via a polite live region", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <DataTable caption="t" columns={COLUMNS} rows={ROWS} />
    );
    await user.click(screen.getByRole("button", { name: "Value" }));
    const live = container.querySelector('[aria-live="polite"]');
    expect(live).toHaveTextContent("Sorted by Value, descending");
  });
});

describe("DataTable R2 extension props", () => {
  it("presorted: trusts caller row order but still stamps aria-sort via controlled sort", async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();
    // rows deliberately NOT in name order — presorted must not reorder
    render(
      <DataTable
        caption="t"
        columns={COLUMNS}
        rows={ROWS}
        presorted
        sort={{ key: "name", direction: "asc" }}
        onSortChange={onSortChange}
      />
    );
    expect(bodyCellText(0)).toEqual(["Chase", "Jefferson", "Bijan"]);
    expect(
      screen.getByRole("columnheader", { name: "Player" })
    ).toHaveAttribute("aria-sort", "ascending");
    await user.click(screen.getByRole("button", { name: "Player" }));
    expect(onSortChange).toHaveBeenCalledWith({ key: "name", direction: "desc" });
  });

  it("firstDirection overrides the first-activation direction", async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();
    const columns = [
      { key: "rank", header: "Rk", numeric: true, sortable: true, firstDirection: "asc" },
      ...COLUMNS,
    ];
    render(
      <DataTable
        caption="t"
        columns={columns}
        rows={ROWS.map((r, i) => ({ ...r, rank: i + 1 }))}
        presorted
        sort={null}
        onSortChange={onSortChange}
      />
    );
    // numeric column would default to desc; firstDirection forces asc
    await user.click(screen.getByRole("button", { name: "Rk" }));
    expect(onSortChange).toHaveBeenCalledWith({ key: "rank", direction: "asc" });
  });

  it("renderBeforeRow / renderAfterRow interleave caller-authored rows", () => {
    render(
      <DataTable
        caption="t"
        columns={COLUMNS}
        rows={ROWS}
        renderBeforeRow={(row, i) =>
          i === 1 ? (
            <tr data-testid="separator">
              <td colSpan={3}>Tier break</td>
            </tr>
          ) : null
        }
        renderAfterRow={(row) =>
          row.id === "a" ? (
            <tr data-testid="expanded">
              <td colSpan={3}>Audit for {row.name}</td>
            </tr>
          ) : null
        }
      />
    );
    const rows = screen.getAllByRole("row");
    // header + 3 data + 1 separator + 1 expanded
    expect(rows).toHaveLength(6);
    expect(screen.getByTestId("expanded")).toHaveTextContent("Audit for Chase");
    // the separator precedes the second data row
    const separator = screen.getByTestId("separator");
    const secondDataRow = screen.getByText("Jefferson").closest("tr");
    expect(
      separator.compareDocumentPosition(secondDataRow) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("rowClassName adds caller classes", () => {
    render(
      <DataTable
        caption="t"
        columns={[{ key: "name", header: "Player" }]}
        rows={ROWS}
        rowClassName={(row) => (row.id === "b" ? "is-flagged" : "")}
      />
    );
    expect(screen.getByText("Jefferson").closest("tr")).toHaveClass("is-flagged");
    expect(screen.getByText("Chase").closest("tr")).not.toHaveClass("is-flagged");
  });

  it("headerInfo renders a tappable InfoTip instead of a native title", async () => {
    // This replaced `headerTitle`, which set a native tooltip: invisible
    // on touch and to screen readers, so on a phone a column header was
    // an abbreviation with no way to find out what it meant.
    const user = userEvent.setup();
    render(
      <DataTable
        caption="t"
        columns={[{ key: "name", header: "Player", headerInfo: "who dis" }]}
        rows={ROWS}
      />
    );
    const th = screen.getByRole("columnheader", { name: /Player/ });
    expect(th).not.toHaveAttribute("title");
    const trigger = screen.getByRole("button", { name: "What is Player?" });
    expect(screen.queryByText("who dis")).toBeNull();
    await user.click(trigger);
    expect(screen.getByText("who dis")).toBeInTheDocument();
  });

  it("headerInfoLabel names the tip when the header is an abbreviation", () => {
    render(
      <DataTable
        caption="t"
        columns={[
          {
            key: "mdv",
            header: "MDV",
            headerInfo: "Marginal dollar value",
            headerInfoLabel: "MDV (marginal dollar value)",
          },
        ]}
        rows={ROWS}
      />
    );
    expect(
      screen.getByRole("button", { name: "What is MDV (marginal dollar value)?" })
    ).toBeInTheDocument();
  });

  it("align center applies the center cell class to th and td", () => {
    render(
      <DataTable
        caption="t"
        columns={[{ key: "pos", header: "Pos", align: "center" }]}
        rows={ROWS}
      />
    );
    expect(screen.getByRole("columnheader", { name: "Pos" })).toHaveClass(
      "ds-table__cell--center"
    );
    const firstRow = screen.getAllByRole("row")[1];
    expect(within(firstRow).getAllByRole("cell")[0]).toHaveClass(
      "ds-table__cell--center"
    );
  });
});

describe("sortRows helper", () => {
  it("sinks null/empty values to the bottom in both directions", () => {
    const rows = [
      { v: 2 },
      { v: null },
      { v: 1 },
      { v: undefined },
      { v: 3 },
    ];
    const cols = [{ key: "v", numeric: true }];
    expect(
      sortRows(rows, cols, { key: "v", direction: "asc" }).map((r) => r.v)
    ).toEqual([1, 2, 3, null, undefined]);
    expect(
      sortRows(rows, cols, { key: "v", direction: "desc" }).map((r) => r.v)
    ).toEqual([3, 2, 1, null, undefined]);
  });

  it("is stable for equal keys", () => {
    const rows = [
      { id: 1, v: 5 },
      { id: 2, v: 5 },
      { id: 3, v: 5 },
    ];
    const cols = [{ key: "v", numeric: true }];
    expect(
      sortRows(rows, cols, { key: "v", direction: "desc" }).map((r) => r.id)
    ).toEqual([1, 2, 3]);
  });
});

describe("DataTable structure & interaction", () => {
  it("applies numeric alignment class to numeric header and cells", () => {
    render(<DataTable caption="t" columns={COLUMNS} rows={ROWS} />);
    expect(
      screen.getByRole("columnheader", { name: "Value" })
    ).toHaveClass("ds-table__cell--num");
    const firstRow = screen.getAllByRole("row")[1];
    expect(within(firstRow).getAllByRole("cell")[1]).toHaveClass(
      "ds-table__cell--num"
    );
  });

  it("supports compact density", () => {
    render(
      <DataTable caption="t" columns={COLUMNS} rows={ROWS} density="compact" />
    );
    expect(screen.getByRole("table")).toHaveClass("ds-table--compact");
  });

  it("renders a visually-hidden caption", () => {
    render(<DataTable caption="Value board" columns={COLUMNS} rows={ROWS} />);
    const caption = screen.getByText("Value board");
    expect(caption.tagName).toBe("CAPTION");
    expect(caption).toHaveClass("ds-visually-hidden");
  });

  it("interactive rows are focusable and activate on Enter and Space", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(
      <DataTable
        caption="t"
        columns={COLUMNS}
        rows={ROWS}
        onRowClick={onRowClick}
      />
    );
    const row = screen.getAllByRole("row")[1];
    expect(row).toHaveAttribute("tabindex", "0");
    row.focus();
    await user.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
    await user.keyboard(" ");
    expect(onRowClick).toHaveBeenCalledTimes(2);
  });

  it("clicks on interactive cell content do NOT activate the row", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    const onCellAction = vi.fn();
    const columns = [
      ...COLUMNS,
      {
        key: "actions",
        header: "Actions",
        render: (r) => (
          <button type="button" onClick={() => onCellAction(r.id)}>
            Compare
          </button>
        ),
      },
    ];
    render(
      <DataTable
        caption="t"
        columns={columns}
        rows={ROWS}
        onRowClick={onRowClick}
      />
    );
    // cell button fires its own action only
    await user.click(screen.getAllByRole("button", { name: "Compare" })[0]);
    expect(onCellAction).toHaveBeenCalledWith("a");
    expect(onRowClick).not.toHaveBeenCalled();
    // a plain (non-interactive) cell still activates the row
    await user.click(screen.getByText("Chase"));
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });

  it("keyboard events inside interactive cell content do NOT activate the row", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    const columns = [
      ...COLUMNS,
      {
        key: "bid",
        header: "Bid",
        render: () => <input aria-label="Bid amount" />,
      },
    ];
    render(
      <DataTable
        caption="t"
        columns={columns}
        rows={ROWS}
        onRowClick={onRowClick}
      />
    );
    const input = screen.getAllByRole("textbox", { name: "Bid amount" })[0];
    input.focus();
    await user.keyboard("{Enter} ");
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it("links and role=button widgets in cells are also exempt from row activation", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    const columns = [
      {
        key: "name",
        header: "Player",
        render: (r) => <a href={`/player/${r.id}`}>{r.name}</a>,
      },
      {
        key: "w",
        header: "Widget",
        render: () => (
          <span role="button" tabIndex={0}>
            widget
          </span>
        ),
      },
    ];
    render(
      <DataTable
        caption="t"
        columns={columns}
        rows={[ROWS[0]]}
        onRowClick={onRowClick}
      />
    );
    await user.click(screen.getByRole("link", { name: "Chase" }));
    await user.click(screen.getByRole("button", { name: "widget" }));
    expect(onRowClick).not.toHaveBeenCalled();
  });

  it("hideBelow emits the breakpoint class on BOTH header and body cells", () => {
    const columns = [
      { key: "name", header: "Player" },
      { key: "team", header: "Team", hideBelow: "md" },
      { key: "value", header: "Value", numeric: true, hideBelow: "sm" },
    ];
    render(<DataTable caption="t" columns={columns} rows={ROWS} />);
    const teamTh = screen.getByRole("columnheader", { name: "Team" });
    expect(teamTh).toHaveClass("ds-col-hide-md");
    const valueTh = screen.getByRole("columnheader", { name: "Value" });
    expect(valueTh).toHaveClass("ds-col-hide-sm", "ds-table__cell--num");
    const firstRow = screen.getAllByRole("row")[1];
    const cells = within(firstRow).getAllByRole("cell");
    expect(cells[0]).not.toHaveClass("ds-col-hide-md");
    expect(cells[1]).toHaveClass("ds-col-hide-md");
    expect(cells[2]).toHaveClass("ds-col-hide-sm", "ds-table__cell--num");
  });

  it("renders emptyState instead of a table when rows are empty", () => {
    render(
      <DataTable
        caption="t"
        columns={COLUMNS}
        rows={[]}
        emptyState={<p>No players</p>}
      />
    );
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText("No players")).toBeInTheDocument();
  });

  it("fallback row keys survive sorting: stateful cells stay with their row", async () => {
    const user = userEvent.setup();
    // No `id` field → the default rowKey falls back to the PRE-SORT index.
    const rows = [
      { name: "Chase", value: 9430 },
      { name: "Bijan", value: 9155 },
      { name: "Jefferson", value: 9541 },
    ];
    const columns = [
      { key: "name", header: "Player", sortable: true },
      { key: "value", header: "Value", numeric: true, sortable: true },
      {
        key: "note",
        header: "Note",
        render: (r) => <input aria-label={`note-${r.name}`} />,
      },
    ];
    render(<DataTable caption="t" columns={columns} rows={rows} />);
    await user.type(screen.getByLabelText("note-Chase"), "sell high");
    // sort round-trip: name asc (Bijan, Chase, Jefferson) then value desc
    await user.click(screen.getByRole("button", { name: "Player" }));
    expect(bodyCellText(0)).toEqual(["Bijan", "Chase", "Jefferson"]);
    expect(screen.getByLabelText("note-Chase")).toHaveValue("sell high");
    expect(screen.getByLabelText("note-Bijan")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Value" }));
    expect(bodyCellText(0)).toEqual(["Jefferson", "Chase", "Bijan"]);
    expect(screen.getByLabelText("note-Chase")).toHaveValue("sell high");
    expect(screen.getByLabelText("note-Jefferson")).toHaveValue("");
  });

  it("supports controlled sort", async () => {
    const user = userEvent.setup();
    const onSortChange = vi.fn();
    render(
      <DataTable
        caption="t"
        columns={COLUMNS}
        rows={ROWS}
        sort={{ key: "name", direction: "asc" }}
        onSortChange={onSortChange}
      />
    );
    expect(bodyCellText(0)).toEqual(["Bijan", "Chase", "Jefferson"]);
    await user.click(screen.getByRole("button", { name: "Player" }));
    expect(onSortChange).toHaveBeenCalledWith({
      key: "name",
      direction: "desc",
    });
    // controlled: parent didn't update, order unchanged
    expect(bodyCellText(0)).toEqual(["Bijan", "Chase", "Jefferson"]);
  });
});
