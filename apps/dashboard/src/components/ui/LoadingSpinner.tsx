export function LoadingSpinner({ label = 'Loading...' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-sky-400" />
      <span className="ml-3 text-slate-400 text-sm">{label}</span>
    </div>
  );
}
