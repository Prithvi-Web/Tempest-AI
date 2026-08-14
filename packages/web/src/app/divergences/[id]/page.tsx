import { notFound } from "next/navigation";

import { DivergenceDetailView } from "./view";

export default async function DivergencePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return <DivergenceDetailView divergenceId={Number(id)} />;
}
