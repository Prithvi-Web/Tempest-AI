import { notFound } from "next/navigation";

import { TargetDetailView } from "./view";

export default async function TargetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return <TargetDetailView targetId={Number(id)} />;
}
