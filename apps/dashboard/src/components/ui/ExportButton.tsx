interface ExportButtonProps {
  data: unknown;
  filename: string;
  format: 'json' | 'csv';
  label?: string;
}

export function ExportButton({ data, filename, format, label }: ExportButtonProps) {
  const handleExport = () => {
    let content: string;
    const mime = format === 'json' ? 'application/json' : 'text/csv';
    if (format === 'json') {
      content = JSON.stringify(data, null, 2);
    } else {
      const rows = data as Record<string, unknown>[];
      if (!Array.isArray(rows) || rows.length === 0) return;
      const headers = Object.keys(rows[0] as Record<string, unknown>);
      content = [
        headers.join(','),
        ...rows.map((r) =>
          headers.map((h) => JSON.stringify((r as Record<string, unknown>)[h] ?? '')).join(',')
        ),
      ].join('\n');
    }
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <button
      type="button"
      onClick={handleExport}
      className="px-3 py-1.5 text-xs font-medium rounded bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
    >
      {label ?? `Export ${format.toUpperCase()}`}
    </button>
  );
}
