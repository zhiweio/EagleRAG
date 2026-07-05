import { IngestClient } from "@/components/ingest/IngestClient";
import { setRequestLocale } from "next-intl/server";

export default async function IngestPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  return <IngestClient />;
}
