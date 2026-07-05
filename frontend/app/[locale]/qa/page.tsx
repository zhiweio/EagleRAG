import { QAClient } from "@/components/qa/QAClient";
import { setRequestLocale } from "next-intl/server";

export default async function QAPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  return <QAClient />;
}
