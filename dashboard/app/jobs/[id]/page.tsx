import { JobDetailMonitor } from "../../../components/JobDetailMonitor";

interface JobDetailPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function JobDetailPage({ params }: JobDetailPageProps) {
  const { id } = await params;
  return <JobDetailMonitor jobId={id} />;
}
