import { NextResponse } from "next/server";
import { proxyGet } from "@/lib/backend-proxy";

export async function GET(request) {
  try {
    // Forward the optional stable league key so league-scoped callers
    // (e.g. the trade page's stack effect) get THEIR league's board,
    // not the server-resolved default.  Omitted → backend resolves as
    // before (unchanged for the unscoped DraftCapitalSection).
    const leagueKey = request?.nextUrl?.searchParams?.get("leagueKey");
    // Forward the session cookie. This endpoint answers 200 to anyone, but
    // REDACTS the rookie fields for public callers — `rookieName` and
    // `rookieBoardValue` come back null on all 72 picks. That is not a
    // visible failure anywhere: /draft's auto-sync writes the empty pool
    // onto the workspace, every rookie ends up without a positive
    // `boardValue`, and the Perfect Draft solve drops the whole pool and
    // renders a panel with zero rows. Only bites where Next serves /api/*
    // itself (dev, E2E); nginx routes past this file in production.
    const { data, status } = await proxyGet("/api/draft-capital", {
      ...(leagueKey ? { searchParams: { leagueKey } } : {}),
      cookie: request.headers.get("cookie") || "",
    });
    return NextResponse.json(data, { status });
  } catch (err) {
    return NextResponse.json(
      { error: "Draft capital service unavailable", detail: err?.message },
      { status: 503 },
    );
  }
}
