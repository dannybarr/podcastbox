import { redirect } from "next/navigation";

export default async function EditionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/?library=1&podcast=${id}`);
}
