export function EmptyState({ title, description }: { title: string; description?: string }) {
  return (
    <div className="text-center py-12">
      <p className="text-slate-400 text-lg font-medium">{title}</p>
      {description && <p className="text-slate-500 text-sm mt-1">{description}</p>}
    </div>
  );
}
