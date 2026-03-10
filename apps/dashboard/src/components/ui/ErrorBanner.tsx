export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 flex items-center gap-3">
      <span className="text-red-400 text-sm font-medium">Error: {message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="text-xs text-red-300 underline hover:text-red-200"
        >
          Retry
        </button>
      )}
    </div>
  );
}
