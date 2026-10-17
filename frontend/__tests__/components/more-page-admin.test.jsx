/**
 * /more (the site map) offers the admin-only Ops surfaces — /admin,
 * /admin/model-lab, /tools/* — to admins only, through the SAME
 * `systemItemsFor({ isAdmin })` filter TopBar and MobileChrome use.
 * The backend 403s non-admins anyway; offering a door that is always
 * locked is worse than not showing it (see SYSTEM_MODEL in lib/nav-model).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";

const auth = { value: { authenticated: true, isAdmin: false, features: null, logout: () => {} } };
vi.mock("@/app/AppShellWrapper", () => ({ useAuthContext: () => auth.value }));

import MorePage from "@/app/more/page";
import { SYSTEM_MODEL } from "@/lib/nav-model";

const OPS = SYSTEM_MODEL.items.filter((i) => i.adminOnly);

afterEach(cleanup);

const linkHrefs = () => screen.getAllByRole("link").map((a) => a.getAttribute("href"));

describe("/more — admin-only Ops destinations", () => {
  it("are hidden from a signed-in non-admin", () => {
    auth.value = { ...auth.value, isAdmin: false };
    render(<MorePage />);
    const hrefs = linkHrefs();
    expect(hrefs).toContain("/settings");
    for (const item of OPS) expect(hrefs, item.href).not.toContain(item.href);
  });

  it("are listed for an admin, Model Lab included", () => {
    auth.value = { ...auth.value, isAdmin: true };
    render(<MorePage />);
    expect(OPS.map((i) => i.href)).toContain("/admin/model-lab");
    const hrefs = linkHrefs();
    for (const item of OPS) expect(hrefs, item.href).toContain(item.href);
  });
});
