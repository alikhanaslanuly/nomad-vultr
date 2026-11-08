import { JobView } from "@/features/job-view";

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JobView key={id} id={id} />;
}
