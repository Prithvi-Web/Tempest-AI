import { parseVerdict } from "@/lib/verdict";

import { RunsListView } from "./runs-list-view";

/** Server wrapper: the URL is the filter state (`?verdict=`, `?cursor=`); the view is client. */
export default async function Home({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const verdict = parseVerdict(typeof sp.verdict === "string" ? sp.verdict : undefined);
  const cursor = typeof sp.cursor === "string" ? sp.cursor : undefined;
  return <RunsListView verdict={verdict} cursor={cursor} />;
}
