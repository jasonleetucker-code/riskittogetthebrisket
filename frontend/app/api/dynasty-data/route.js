import { NextResponse } from "next/server";
import { loadDynastySource } from "../../../lib/dynasty-source";

export async function GET() {
  const payload = await loadDynastySource();
  if (payload.ok) return NextResponse.json(payload);
  if (payload?.errorCode === "backend_unavailable") {
    return NextResponse.json(payload, { status: 503 });
  }
  return NextResponse.json(payload, { status: 404 });
}
