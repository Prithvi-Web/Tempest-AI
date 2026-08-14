import { notFound } from "next/navigation";

import { RunDetailView } from "./view";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return <RunDetailView runId={Number(id)} />;
}
